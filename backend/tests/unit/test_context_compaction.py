"""Automatic context compaction, from docs/plans/automatic-context-compaction.md.

Written 2026-09-07, after a status sweep found the three modules live in
production with no test asserting anything about them, and Tier 2 written,
imported and constructed by nobody. The last test in this file is the one that
would have caught that, and it is the reason the file exists at all: the tiers
themselves are pure functions and easy to believe, while the wiring is the part
that was actually wrong.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.route_chat_request.compaction import (
    RECENT_MESSAGE_WINDOW,
    TOOL_DESCRIPTION_CAP,
    CompactionDisclosure,
    try_compact,
)
from app.application.use_cases.route_chat_request.compaction_cache import (
    CompactionCache,
)
from app.application.use_cases.route_chat_request.compaction_cache import (
    CompactionResult as CachedPrefix,
)
from app.application.use_cases.route_chat_request.compaction_tier2 import try_tier2
from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.exceptions import ContextTooLongError
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.infrastructure.config import get_settings
from app.infrastructure.di.inference_runtime import build_route_chat_request
from app.interfaces.http import sse
from app.interfaces.http.request_context import report_compaction, reset_compaction
from app.interfaces.http.sse.encoding import compaction_header
from tests.unit.streaming_contract_fixtures import ACTOR, FakeRuntime, _run, build

pytest_plugins = ("tests.unit.streaming_contract_fixtures",)


def _compaction_reset() -> None:
    """What `RequestContextMiddleware` does at the start of every request.

    Called explicitly because these tests share a task, so a value left from the
    previous one would let a test pass by reading another test's compaction.
    """
    reset_compaction()


TARGET = Model(
    id="m1",
    alias="primary",
    ref="primary:latest",
    runtime=RuntimeKind.OLLAMA,
    node_id="n1",
    state=ModelState.LOADED,
    capabilities=frozenset({"chat"}),
    resource_profile=ResourceProfile(memory_gb=8.0, context_length=8192),
)


def _tool(name: str, description: str = "does a thing") -> ToolDefinition:
    return ToolDefinition(name=name, description=description, parameters={"type": "object"})


def _counter(*values: int | None):
    """A count_fn returning the given values in order, then the last forever.

    Compaction re-counts after every tier, so a test that wants "tier 0 was not
    enough but tier 1 was" is describing a sequence of counts rather than a
    single number.
    """
    remaining = list(values)

    async def count_fn(target, messages, tools):
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return count_fn


# --- Tier 0: tool definitions -------------------------------------------


async def test_tier_0_keeps_the_last_definition_of_a_duplicated_name() -> None:
    """The last one is what the model would have acted on, so it is the one
    that survives. Keeping the first would change behaviour while claiming to
    have only removed a duplicate."""
    tools = [_tool("search", "old wording"), _tool("read"), _tool("search", "new wording")]

    result = await try_compact(
        messages=[Message(role=MessageRole.USER, content="hi")],
        tools=tools,
        counted=500,
        limit=100,
        count_fn=_counter(50),
        target=TARGET,
    )

    assert result is not None
    assert result.tier == 0
    by_name = {t.name: t.description for t in result.tools}
    assert by_name["search"] == "new wording"
    assert len(result.tools) == 2
    assert "1 duplicate tool definition removed" in result.disclosure


async def test_tier_0_trims_descriptions_but_never_names_or_schemas() -> None:
    """Trimming is safe precisely because it cannot reach the two things a
    model needs to produce a valid call."""
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    long = ToolDefinition(name="search", description="x" * 900, parameters=schema)

    result = await try_compact(
        messages=[Message(role=MessageRole.USER, content="hi")],
        tools=[long],
        counted=500,
        limit=100,
        count_fn=_counter(50),
        target=TARGET,
    )

    assert result is not None
    kept = result.tools[0]
    assert kept.name == "search"
    assert kept.parameters == schema
    assert len(kept.description) == TOOL_DESCRIPTION_CAP + 1  # the ellipsis
    assert f"trimmed to {TOOL_DESCRIPTION_CAP} characters" in result.disclosure


async def test_nothing_to_compact_is_not_a_compaction() -> None:
    """A short unique tool list and no old tool results means every tier is a
    no-op, and the honest answer is None — the caller refuses. Returning a
    result here would report a compaction that removed nothing."""
    result = await try_compact(
        messages=[Message(role=MessageRole.USER, content="hi")],
        tools=[_tool("search")],
        counted=500,
        limit=100,
        count_fn=_counter(500),
        target=TARGET,
    )

    assert result is None


# --- Tier 1: old tool results -------------------------------------------


def _agent_history(n_tool_results: int, payload_chars: int = 4000) -> list[Message]:
    """A conversation whose bulk is tool output, which is the shape §5.2 is
    about."""
    messages: list[Message] = [Message(role=MessageRole.SYSTEM, content="you are a tool user")]
    for i in range(n_tool_results):
        messages.append(
            Message(role=MessageRole.ASSISTANT, content=f"calling search for the {i}th time")
        )
        messages.append(
            Message(
                role=MessageRole.TOOL,
                content="f" * payload_chars,
                tool_call_id=f"call_{i}",
                name="search",
            )
        )
    return messages


async def test_tier_1_replaces_old_tool_results_with_a_marker_that_says_what_was_there() -> None:
    """A marker naming the size and the call is information the model can act
    on; an absence is not. That is the whole argument for a marker over a
    deletion."""
    messages = _agent_history(12)

    result = await try_compact(
        messages=messages,
        tools=[_tool("search")],
        counted=50_000,
        limit=1000,
        # Tier 0 has nothing to do here, so the first re-count is tier 1's.
        count_fn=_counter(900),
        target=TARGET,
    )

    assert result is not None
    assert result.tier == 1
    marker = result.messages[2]
    assert marker.role is MessageRole.TOOL
    assert "tool result removed" in marker.content
    assert "4000 characters" in marker.content
    assert "call_0" in marker.content
    # The pairing survives, which is what lets the runtime match this to the
    # assistant message that asked for it.
    assert marker.tool_call_id == "call_0"
    assert marker.name == "search"


async def test_tier_1_leaves_the_recent_window_alone() -> None:
    """The window protects the results the model is currently reasoning about.
    Compacting those would be compacting the answer to the question being
    asked."""
    messages = _agent_history(12)

    result = await try_compact(
        messages=messages,
        tools=[_tool("search")],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
    )

    assert result is not None
    for original, produced in zip(
        messages[-RECENT_MESSAGE_WINDOW:], result.messages[-RECENT_MESSAGE_WINDOW:], strict=True
    ):
        assert produced.content == original.content


async def test_a_short_tool_result_is_not_worth_a_marker() -> None:
    """Below 80 characters the marker costs more than the payload, so replacing
    it would grow the prompt it was called to shrink."""
    messages = _agent_history(12, payload_chars=20)

    result = await try_compact(
        messages=messages,
        tools=[_tool("search")],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
    )

    assert result is None


async def test_the_tiers_stop_at_the_first_that_is_enough() -> None:
    """Cheapest first, and stop: a request that tier 0 rescues must never pay
    tier 1's loss of a tool result."""
    messages = _agent_history(12)

    result = await try_compact(
        messages=messages,
        tools=[_tool("search", "y" * 900), _tool("search", "z" * 900)],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
    )

    assert result is not None
    assert result.tier == 0
    # No marker anywhere: tier 1 never ran.
    assert all("tool result removed" not in m.content for m in result.messages)


async def test_a_disclosure_accumulates_across_tiers() -> None:
    """Reaching tier 1 does not undo tier 0, so what the caller is owed is both
    facts rather than the last one."""
    messages = _agent_history(12)

    result = await try_compact(
        messages=messages,
        tools=[_tool("search", "y" * 900), _tool("search", "z" * 900)],
        counted=50_000,
        limit=1000,
        count_fn=_counter(5000, 900),
        target=TARGET,
    )

    assert result is not None
    assert result.tier == 1
    assert "Tier 0:" in result.disclosure
    assert "Tier 1:" in result.disclosure


# --- Tier 2: summarisation ----------------------------------------------


class RecordingSummariser:
    def __init__(self, summary: str = "the user asked about seats") -> None:
        self.calls: list[int] = []
        self._summary = summary

    async def __call__(self, messages) -> str:
        self.calls.append(len(messages))
        return self._summary


class MemoryCache:
    """A CachePort over a dict. TTLs are recorded rather than honoured; nothing
    here tests expiry, and a sleeping test would be worse than no test."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[key] = value
        self.ttls[key] = ttl_seconds

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def incr(self, key: str, ttl_seconds: int) -> int:
        raise AssertionError("compaction never counts")


async def test_tier_2_summarises_the_oldest_turns_and_keeps_the_recent_ones() -> None:
    messages = _agent_history(12)
    summariser = RecordingSummariser()

    result = await try_tier2(
        messages=messages,
        tools=[],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
        summarise_fn=summariser,
        cache=None,
        lock=asyncio.Lock(),
    )

    assert result is not None
    assert result.tier == 2
    assert result.messages[0].role is MessageRole.SYSTEM
    assert "Compacted summary" in result.messages[0].content
    assert "the user asked about seats" in result.messages[0].content
    # 25 messages and 6 to keep leaves 19, floored to a multiple of the step:
    # 10 summarised, and 15 kept verbatim rather than the window's minimum of
    # 6. Erring towards keeping more of the conversation is the safe direction
    # for a boundary that has to be stable.
    assert summariser.calls == [10]
    assert list(result.messages[1:]) == messages[10:]


async def test_tier_2_declines_a_conversation_with_nothing_old_in_it() -> None:
    """Six messages or fewer is all recent window. Summarising there would
    replace the conversation with a description of itself."""
    result = await try_tier2(
        messages=[Message(role=MessageRole.USER, content="hi")] * 4,
        tools=[],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
        summarise_fn=RecordingSummariser(),
        cache=None,
        lock=asyncio.Lock(),
    )

    assert result is None


async def test_a_summary_that_is_still_too_long_refuses_rather_than_serving() -> None:
    """The last tier failing means the prompt does not fit. Returning it anyway
    would hand the runtime a prompt over the ceiling, and the runtime truncates
    silently — which is the failure the whole plan is about."""
    result = await try_tier2(
        messages=_agent_history(12),
        tools=[],
        counted=50_000,
        limit=1000,
        count_fn=_counter(40_000),
        target=TARGET,
        summarise_fn=RecordingSummariser(),
        cache=None,
        lock=asyncio.Lock(),
    )

    assert result is None


# --- The cache, without which none of it works ---------------------------


async def test_the_second_turn_of_a_conversation_does_not_summarise_again() -> None:
    """§5.4, and the single most important detail in the plan. The gateway is
    stateless and the client replays the history, so without this the same
    prefix is summarised on every turn — an inference call per turn on a
    one-slot runtime, which is an outage rather than a slow feature.

    This is the test that found the boundary bug: the prefix was measured from
    the end of a conversation that grows every turn, so the key changed every
    turn and the cache never hit. It only passes now because the boundary is
    quantised (`_PREFIX_STEP`).
    """
    cache = CompactionCache(MemoryCache())
    summariser = RecordingSummariser()
    # 29 messages: 23 summarisable, so the floored boundary is 20 and stays
    # there while the next turn adds two. Crossing a threshold does recompute,
    # which is the design — "reused until it grows past the next threshold".
    messages = _agent_history(14)

    first = await try_tier2(
        messages=messages,
        tools=[],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
        summarise_fn=summariser,
        cache=cache,
        lock=asyncio.Lock(),
    )
    # The next turn: the client replays everything and adds two messages.
    next_turn = [
        *messages,
        Message(role=MessageRole.USER, content="and then?"),
        Message(role=MessageRole.ASSISTANT, content="then this"),
    ]
    second = await try_tier2(
        messages=next_turn,
        tools=[],
        counted=50_000,
        limit=1000,
        count_fn=_counter(900),
        target=TARGET,
        summarise_fn=summariser,
        cache=cache,
        lock=asyncio.Lock(),
    )

    assert first is not None and second is not None
    assert summariser.calls == [20], "the prefix was summarised twice"
    assert second.disclosure == first.disclosure


async def test_a_different_prefix_is_a_different_key() -> None:
    """Content-addressed means exactly that: two conversations that share a
    length but not a history must not share a summary.

    The difference has to be inside the summarised prefix to count. Two
    conversations differing only in their most recent turn genuinely *do* share
    a prefix, and sharing the summary of it is the feature.
    """
    backing = MemoryCache()
    cache = CompactionCache(backing)
    summariser = RecordingSummariser()

    for filler in ("a", "b"):
        await try_tier2(
            messages=[Message(role=MessageRole.SYSTEM, content=filler)]
            + _agent_history(12, payload_chars=4000),
            tools=[],
            counted=50_000,
            limit=1000,
            count_fn=_counter(900),
            target=TARGET,
            summarise_fn=summariser,
            cache=cache,
            lock=asyncio.Lock(),
        )

    assert len(summariser.calls) == 2
    assert len(backing.store) == 2


async def test_a_cached_prefix_survives_a_round_trip_through_redis() -> None:
    """The value is JSON in a string, so the roles and the tool pairing have to
    come back as they went in. They are read straight back into a prompt."""
    backing = MemoryCache()
    cache = CompactionCache(backing)
    messages = [Message(role=MessageRole.TOOL, content="x" * 200, tool_call_id="c1", name="search")]

    await cache.put(
        messages,
        [],
        tier=2,
        result=CachedPrefix(
            messages=(Message(role=MessageRole.SYSTEM, content="a summary"),),
            disclosure="Tier 2: 1 message summarised",
            tier=2,
            tokens_before=100,
            tokens_after=10,
        ),
    )
    back = await cache.get(messages, [], tier=2)

    assert back is not None
    assert back.messages[0].role is MessageRole.SYSTEM
    assert back.messages[0].content == "a summary"
    assert back.tokens_before == 100
    key = next(iter(backing.store))
    assert backing.ttls[key] == 3600


async def test_a_corrupt_cache_entry_is_a_miss_rather_than_a_crash() -> None:
    """A cache is a cache: losing an entry costs a recomputation. Anything it
    can do to a live request other than that is a bug."""
    backing = MemoryCache()
    cache = CompactionCache(backing)
    messages = [Message(role=MessageRole.USER, content="hi")]

    await cache.put(
        messages,
        [],
        tier=2,
        result=CachedPrefix(
            messages=(Message(role=MessageRole.SYSTEM, content="s"),),
            disclosure="d",
            tier=2,
            tokens_before=1,
            tokens_after=1,
        ),
    )
    key = next(iter(backing.store))
    backing.store[key] = json.dumps({"unexpected": "shape"})

    assert await cache.get(messages, [], tier=2) is None


# --- Through the orchestrator -------------------------------------------


class SteppedCounter:
    """A token counter whose answer falls as the prompt is compacted.

    A fixed counter cannot express compaction at all: the guardrail counts, a
    tier runs, and the same number comes back, so nothing ever fits and every
    test is a refusal.
    """

    def __init__(self, *values: int) -> None:
        self._values = list(values)
        self.asked = 0

    async def prepare(self, ref: str) -> bool:
        return True

    async def count_prompt(self, ref, messages, tools) -> int | None:
        self.asked += 1
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]

    async def count_parts(self, ref, texts) -> list[int] | None:
        return None


async def test_a_compacted_request_records_the_tier_on_its_usage_row() -> None:
    """The `usage_records` columns are the only durable evidence that a prompt
    was reduced. A row that does not carry the tier makes "which requests were
    compacted, and how hard?" an investigation rather than a query."""
    runtime = FakeRuntime(chunks=1)
    use_case, usage, _ = build(
        runtime,
        # Above the character lower bound of this history, which is checked
        # before a slot is held and would otherwise refuse first.
        max_context_tokens=10_000,
        tokens=SteppedCounter(50_000, 900),
    )

    await _run(use_case, messages=_agent_history(12), tools=[_tool("search")])

    assert len(usage.records) == 1
    assert usage.records[0].compaction_tier == 1
    assert usage.records[0].tokens_before_compaction == 50_000
    assert usage.records[0].tokens_after_compaction == 900


async def test_a_key_with_compaction_off_is_refused_rather_than_compacted() -> None:
    """The switch is the whole of what §5.5 shipped, and an integration that
    turned it off did so to see the refusal."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime,
        max_context_tokens=10_000,
        tokens=SteppedCounter(50_000, 900),
    )
    no_compaction = replace(ACTOR, compaction_enabled=False)

    with pytest.raises(ContextTooLongError):
        async with aclosing(
            use_case.execute(no_compaction, "chat", _agent_history(12), tools=[_tool("search")])
        ) as stream:
            async for _ in stream:
                pass


async def test_an_uncompactable_prompt_is_still_refused() -> None:
    """Compaction removes a refusal that had no remedy; it must not remove one
    that does. A prompt the tiers cannot bring under the ceiling has to meet
    the same `ContextTooLongError` it always did, because the alternative is
    handing the runtime a prompt it will truncate in silence."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=10_000, tokens=SteppedCounter(50_000))

    with pytest.raises(ContextTooLongError):
        await _run(use_case, messages=_agent_history(12), tools=[_tool("search")])


async def test_a_summariser_that_fails_refuses_instead_of_returning_a_500() -> None:
    """Tier 2 reaches a routing policy, a registry, a node and another model's
    runtime. Any of those being unavailable is a reason to refuse this caller
    at the ceiling, and never a reason to answer them with the uncompacted
    prompt or with an internal error."""

    async def explode(messages):
        raise RuntimeError("assist is down")

    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime,
        max_context_tokens=1000,
        # Nothing tiers 0 and 1 can do: no tools, no old tool results.
        tokens=SteppedCounter(5000),
        summarise_fn=explode,
    )

    with pytest.raises(ContextTooLongError):
        await _run(
            use_case,
            messages=[Message(role=MessageRole.USER, content=f"turn {i}") for i in range(30)],
        )


async def test_tier_2_reaches_the_runtime_when_the_tiers_before_it_are_not_enough() -> None:
    """The end-to-end path the plan describes, in one test: tiers 0 and 1 leave
    the prompt over the ceiling, the summariser runs on something that is not
    the serving model, and the request is served."""
    summariser = RecordingSummariser()
    runtime = FakeRuntime(chunks=1)
    use_case, usage, _ = build(
        runtime,
        max_context_tokens=10_000,
        tokens=SteppedCounter(50_000, 40_000, 900),
        summarise_fn=summariser,
    )

    await _run(use_case, messages=_agent_history(12), tools=[_tool("search")])

    assert summariser.calls == [10]
    assert usage.records[0].compaction_tier == 2


# --- The wiring, which is the part that was actually broken --------------


async def test_the_composition_root_builds_every_compaction_collaborator(monkeypatch) -> None:
    """The regression test for the whole of §9.2.

    `compaction_tier2.py` and `compaction_cache.py` were written on 2026-09-05,
    imported by the orchestrator, and passed by nothing: the orchestrator calls
    Tier 2 only when `summarise_fn is not None`, and `build_route_chat_request`
    passed none of the three. So 379 lines shipped, every test above this one
    would still have passed, and no deployment ever ran a line of it.

    The lock is asserted to be the one on `app.state` and not merely present,
    because the orchestrator's default builds a lock per instance and
    `build_route_chat_request` is a per-request dependency — a per-request lock
    serialises exactly nothing, which is the failure this assertion exists to
    name.
    """
    # The prompt-log writer wants a real session factory and nothing here
    # writes one; the compaction collaborators are what this test is about.
    monkeypatch.setattr("app.infrastructure.di.inference_runtime.get_session_factory", lambda: None)

    app = FastAPI()
    app.state.runtimes = {}
    app.state.concurrency = SemaphoreConcurrencyLimiter(1)
    app.state.authz = RoleAuthorization()
    app.state.cache = MemoryCache()
    app.state.compaction_lock = asyncio.Lock()

    use_case = build_route_chat_request(
        request=SimpleNamespace(app=app),  # type: ignore[arg-type]
        session=SimpleNamespace(),  # type: ignore[arg-type]
        settings=get_settings(),
    )

    assert use_case._summarise_fn is not None
    assert use_case._compaction_cache is not None
    assert use_case._compaction_lock is app.state.compaction_lock


async def test_both_entrances_put_the_compaction_lock_on_app_state() -> None:
    """One process, one lock. The gateway and the admin entrances each run
    inference, so a lock missing from either is a serialisation guarantee that
    holds on one entrance and not the other."""
    for module in ("app.infrastructure.main_gateway", "app.infrastructure.admin_composition"):
        source = Path(import_module(module).__file__).read_text()
        assert "app.state.compaction_lock = asyncio.Lock()" in source, module


# --- The disclosure, which is what §3 asked for ---------------------------


async def test_a_compacted_request_announces_itself_in_a_header() -> None:
    """§3, and the requirement the plan called the one place it amends the
    request: on by default, and never silent.

    The header rather than a body field because the envelope is OpenAI's and an
    extra frame shape is a protocol error to a strict client — the same
    reasoning, and the same channel, as `X-Capability-Defaulted`,
    `X-Dropped-Tools` and `X-Knowledge-Sources`.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime,
        max_context_tokens=10_000,
        tokens=SteppedCounter(50_000, 900),
        report_compaction=report_compaction,
    )

    _compaction_reset()
    await _run(use_case, messages=_agent_history(12), tools=[_tool("search")])

    assert compaction_header() == {sse.COMPACTION_HEADER: "tier=1"}


async def test_an_ordinary_request_carries_no_compaction_header() -> None:
    """The header is a narrowing notice. On a request nothing narrowed it must
    be absent rather than present and empty, which is what every other header of
    this family does."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=10_000, report_compaction=report_compaction)

    _compaction_reset()
    await _run(use_case)

    assert compaction_header() == {}


async def test_a_refused_request_announces_nothing() -> None:
    """Compaction that could not bring the prompt under the ceiling is not a
    compaction: the request was refused, and a header saying the prompt had been
    reduced would describe a response that was never served."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime,
        max_context_tokens=10_000,
        tokens=SteppedCounter(50_000),
        report_compaction=report_compaction,
    )

    _compaction_reset()
    with pytest.raises(ContextTooLongError):
        await _run(use_case, messages=_agent_history(12), tools=[_tool("search")])

    assert compaction_header() == {}


async def test_the_disclosure_that_leaves_the_use_case_carries_no_prompt() -> None:
    """What crosses out of the application layer is three integers.

    `CompactionResult` holds the compacted messages and tools, and handing that
    to the HTTP layer so it could render a header would put the whole prompt
    somewhere that needs a number. The separate type is the boundary.
    """
    seen: list[CompactionDisclosure] = []
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime,
        max_context_tokens=10_000,
        tokens=SteppedCounter(50_000, 900),
        report_compaction=seen.append,
    )

    await _run(use_case, messages=_agent_history(12), tools=[_tool("search")])

    assert len(seen) == 1
    assert seen[0] == CompactionDisclosure(tier=1, tokens_before=50_000, tokens_after=900)
    assert not hasattr(seen[0], "messages")
