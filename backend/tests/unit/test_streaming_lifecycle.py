from __future__ import annotations

from contextlib import aclosing

import pytest

from tests.unit.streaming_contract_fixtures import (
    ACTOR,
    MESSAGES,
    FakeMonotonic,
    FakeRuntime,
    OllamaShapedRuntime,
    SlowRuntime,
    SlowToStartRuntime,
    ThinkingRecordingRuntime,
    _run,
    build,
)

pytest_plugins = ("tests.unit.streaming_contract_fixtures",)


async def test_full_stream_records_usage_and_releases_slot() -> None:
    runtime = FakeRuntime(chunks=3)
    use_case, usage, limiter = build(runtime)

    collected = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            collected.append(chunk.delta)

    assert len(collected) == 3
    assert limiter.available == limiter.limit, "slot must be released"
    assert usage.records[0].tokens == 3
    assert usage.records[0].completed is True


async def test_the_selected_model_s_context_length_reaches_the_runtime() -> None:
    """Routing knows which model was chosen; the runtime has to be told its size.

    `ManageModels.load` sizes the runner from the registered profile, and a
    generation that omitted the same figure would start a second runner at the
    model's own maximum — undoing the load's restraint on the first request
    rather than at load. See `middleware`-free note in PROGRESS.md 2026-08-07.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime)

    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for _ in stream:
            pass

    assert runtime.seen_context_length == 8192, "the model's registered profile, not a default"


async def test_client_disconnect_releases_slot_and_bills_partial_output() -> None:
    """Abandoning the stream after one chunk must not leak the slot.

    This is why every consumer wraps iteration in `aclosing()`: the `finally`
    inside the async generator only runs when the generator is closed.
    """
    runtime = FakeRuntime(chunks=100)
    use_case, usage, limiter = build(runtime, limit=1)

    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for _ in stream:
            break  # simulate the client going away

    assert limiter.available == limiter.limit, "slot leaked on early exit"
    assert runtime.cleaned_up is True, "adapter never closed its upstream stream"
    assert usage.records, "partial output must still be recorded"
    assert usage.records[0].completed is False
    assert usage.records[0].tokens == 1


async def test_upstream_error_still_releases_slot_and_records_usage() -> None:
    runtime = FakeRuntime(chunks=5, fail_at=2)
    use_case, usage, limiter = build(runtime)

    with pytest.raises(RuntimeError):
        async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
            async for _ in stream:
                pass

    assert limiter.available == limiter.limit
    assert usage.records[0].completed is False
    assert usage.records[0].tokens == 2


async def test_max_tokens_ceiling_is_enforced_regardless_of_runtime() -> None:
    """The cap is ours, not the caller's and not the runtime's."""
    runtime = FakeRuntime(chunks=1000)
    use_case, usage, _ = build(runtime, ceiling=5)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    content = [c for c in chunks if c.delta]
    assert len(content) == 5
    assert usage.records[0].tokens == 5

    # A generation we cut off must not be reported as one the model finished:
    # OpenAI clients branch on this field to decide whether to continue.
    assert chunks[-1].finish_reason == "length"
    assert usage.records[0].completed is False, "truncation is not completion"


async def test_the_token_ceiling_does_not_hide_the_prompt_from_the_quota() -> None:
    """`max_tokens: 1` in front of a context-filling prompt must still be paid for.

    This was the shape of the bypass. Prompt tokens are counted so that a
    caller cannot fill the context window free of quota — but the ceiling check
    ran first and `break` left the runtime's terminal event unread, which is
    the only place the count appears. One token of quota for a hundred thousand
    tokens of work, from the change that existed to prevent exactly that.

    The fix reads on past the ceiling without forwarding, which costs nothing:
    the runtime is told `num_predict = ceiling`, so its terminal event is the
    next one.
    """
    runtime = OllamaShapedRuntime(content_chunks=50, prompt_tokens=500)
    use_case, usage, _ = build(runtime, ceiling=1)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    record = usage.records[0]
    assert record.prompt_tokens == 500, "the prompt was read and must be charged for"
    assert record.tokens == 1, "output above the ceiling was withheld, so it is not billed"

    # Still exactly one terminal frame, and still honest about why it stopped.
    # The drained terminal chunk is not forwarded, so this has to be ours.
    terminal = [c for c in chunks if c.finish_reason]
    assert len(terminal) == 1, "a truncated stream must end once, not zero or twice"
    assert terminal[0].finish_reason == "length"


async def test_a_runtime_that_never_terminates_does_not_hold_the_request_open() -> None:
    """The drain is bounded. A runtime ignoring `num_predict` must not be able
    to keep this generator reading for as long as it feels like streaming."""
    runtime = FakeRuntime(chunks=10_000)  # no terminal chunk, ever
    use_case, usage, limiter = build(runtime, ceiling=5)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    assert len([c for c in chunks if c.delta]) == 5, "the ceiling still holds"
    assert usage.records[0].tokens == 5, "drained chunks are not billed"
    assert usage.records[0].prompt_tokens == 0, "honestly unknown rather than invented"
    assert limiter.available == limiter.limit, "slot released"
    assert runtime.cleaned_up is True


async def test_wall_clock_deadline_cuts_a_slow_stream_below_the_token_ceiling() -> None:
    """A stream that never reaches the token ceiling must still be bounded.

    Ten seconds per token against a 25s deadline and a ceiling well out of
    reach: the slot is what a slow model holds, and the deadline is the only
    guardrail that releases it, since the token ceiling never trips and the
    per-read HTTP timeout never fires while chunks keep arriving.
    """
    clock = FakeMonotonic()
    runtime = SlowRuntime(clock, seconds_per_chunk=10.0)
    use_case, usage, limiter = build(runtime, limit=1, ceiling=1000, deadline=25, monotonic=clock)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    content = [c for c in chunks if c.delta]
    # Four, not three: the clock is at 10s when the first chunk arrives, and
    # since 2026-08-05 the deadline runs from there rather than from the
    # request, so that first interval is prompt evaluation rather than
    # generation. Tokens then land at 0s, 10s and 20s into the budget, and the
    # fourth crosses 25s.
    assert len(content) == 4, "three tokens under the deadline, the fourth crosses it"
    assert chunks[-1].finish_reason == "length", "a deadline cut is not a clean stop"
    assert limiter.available == limiter.limit, "slot must be released on a deadline cut"
    assert runtime.cleaned_up is True, "adapter must close its upstream on a deadline cut"
    assert usage.records[0].completed is False, "a deadline cut is not completion"
    assert usage.records[0].tokens == 4


async def test_reading_a_long_prompt_does_not_spend_the_generation_deadline() -> None:
    """The deadline bounds a stream that produces too slowly to finish, and
    prompt evaluation produces nothing at all.

    Measured from the request it was most of the budget at a large context:
    over 550 seconds of evaluation against a 900 second deadline on this
    hardware, so the stream was cut on its first token and reported
    `finish_reason: "length"` — telling the client the model had talked too much
    when it had not yet started. What bounds prompt evaluation is the per-read
    HTTP timeout, which is the limit designed for "no bytes for the interval".
    """
    clock = FakeMonotonic()
    runtime = SlowToStartRuntime(clock, prompt_seconds=550.0, chunks=3)
    use_case, usage, _ = build(runtime, limit=1, ceiling=1000, deadline=25, monotonic=clock)

    chunks = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            chunks.append(chunk)

    assert chunks[-1].finish_reason == "stop", "a long prompt is not a truncated answer"
    assert len([c for c in chunks if c.delta]) == 3, "every token the model produced"
    assert usage.records[0].completed is True
    # The whole wait is still what the caller experienced, so latency keeps
    # measuring from the request even though the deadline does not.
    assert usage.records[0].latency_ms >= 550_000


async def test_deadline_disabled_by_non_positive_value() -> None:
    """Zero disables the deadline, matching the heartbeat convention. The token
    ceiling remains the bound, so the stream stops there rather than never."""
    clock = FakeMonotonic()
    runtime = SlowRuntime(clock, seconds_per_chunk=10_000.0)
    use_case, usage, _ = build(runtime, limit=1, ceiling=4, deadline=0, monotonic=clock)

    content = []
    async with aclosing(use_case.execute(ACTOR, "chat", MESSAGES)) as stream:
        async for chunk in stream:
            if chunk.delta:
                content.append(chunk)

    assert len(content) == 4, "no deadline, so only the token ceiling stops it"
    assert usage.records[0].tokens == 4


async def test_request_thinking_preference_overrides_the_deployment_default() -> None:
    """The whole point of the per-request switch.

    It cannot be per model: the registry's unique index on (node, runtime, ref)
    forbids registering the same weights twice, and the memory budget would
    count them twice if it did not. So one loaded copy has to serve both, and
    the decision travels with the request.
    """
    runtime = ThinkingRecordingRuntime()
    use_case, _, _ = build(runtime, thinking_default=True)

    await _run(use_case, thinking=False)
    assert runtime.seen == [False], "an explicit false must reach the runtime"

    await _run(use_case, thinking=True)
    assert runtime.seen[-1] is True


async def test_omitting_the_preference_takes_the_configured_default() -> None:
    runtime = ThinkingRecordingRuntime()
    use_case, _, _ = build(runtime, thinking_default=False)

    await _run(use_case)
    assert runtime.seen == [False], "None means defer, not 'think'"

    # And the default does not override an explicit opposite.
    await _run(use_case, thinking=True)
    assert runtime.seen[-1] is True


async def test_thinking_is_not_clamped_the_way_max_tokens_is() -> None:
    """`max_tokens` is clamped because it costs hardware; asking a model not to
    deliberate asks for less work, so there is nothing to protect against and
    the caller's choice stands whatever the default says."""
    runtime = ThinkingRecordingRuntime()
    use_case, _, _ = build(runtime, thinking_default=True)

    await _run(use_case, max_tokens=10**9, thinking=False)
    assert runtime.seen == [False]
