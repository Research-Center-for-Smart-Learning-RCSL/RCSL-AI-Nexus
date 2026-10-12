"""Tier 2 stays on the node, with bounded work and terminal settlement."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.application.use_cases.route_chat_request.compaction_tier2 import (
    SUMMARY_INPUT_MAX_BYTES,
    SUMMARY_MAX_BYTES,
    SUMMARY_OUTPUT_TOKENS,
)
from app.domain.entities.chat import Message, MessageRole
from app.domain.exceptions import NoAvailableModelError, ServerOverloadedError
from app.node_agent.api import create_app
from app.node_agent.dispatch import Completed, Dispatcher, RuntimeRefused, Sink, Uncertain
from app.node_agent.guard import Registration
from app.node_agent.summary import bounded_summary
from tests.unit.test_node_agent_dispatch import MemoryStore


class Counter:
    def __init__(self, counted: int | None = 100, output: int | None = 5) -> None:
        self.counted = counted
        self.output = output
        self.prompts: list[Any] = []

    async def measure(self, ref: str, messages: Any, tools: Any) -> Measurement:
        self.prompts.append(messages)
        return Measurement("manifest", self.counted, 32768)

    async def count_parts(self, ref: str, texts: Any) -> list[int] | None:
        return None if self.output is None else [self.output]


class SummaryRelay:
    def __init__(self, *, text: str = "Summary.", hold: asyncio.Event | None = None) -> None:
        self.text = text
        self.hold = hold
        self.started = asyncio.Event()
        self.payloads: list[Any] = []

    async def version(self) -> str:
        return "0.0.test"

    def chat(self, payload: Any, **kwargs: Any) -> Any:
        self.payloads.append(payload)

        async def run(sink: Sink) -> Any:
            self.started.set()
            if self.hold is not None:
                await self.hold.wait()
            sink.emit({"type": "line", "data": {"message": {"content": self.text}}})
            return Completed({"eval_count": 5, "done_reason": "stop"})

        return run


def summary_app(monkeypatch: pytest.MonkeyPatch, counter: Any, relay: Any) -> Any:
    async def registered(*args: Any) -> Registration:
        return Registration(32768, "manifest", ("assist",))

    monkeypatch.setattr("app.node_agent.api.registration", registered)
    app = create_app()
    store = MemoryStore()
    app.state.agent = SimpleNamespace(
        settings=SimpleNamespace(token="test-agent-token", node_id="n", queue_deadline_s=1),
        counter=counter,
        relay=relay,
        pool=None,
        keep_alive="-1",
        store=store,
        dispatcher=Dispatcher(store),
    )
    return app


def runtime_for(app: Any) -> NodeAgentRuntime:
    return NodeAgentRuntime(
        "http://agent", "test-agent-token", timeout_s=5, transport=httpx.ASGITransport(app=app)
    )


async def test_summary_prompt_and_budget_are_constructed_and_counted_by_the_node(monkeypatch):
    counter = Counter()
    relay = SummaryRelay()
    app = summary_app(monkeypatch, counter, relay)
    runtime = runtime_for(app)
    text = await runtime.summarise("qwen2.5:7b", [Message(MessageRole.USER, "original")], 32768)
    assert text == "Summary."
    assert counter.prompts[0][0].role is MessageRole.SYSTEM
    assert "[user] original" in counter.prompts[0][1].content
    assert relay.payloads[0]["options"]["num_predict"] == SUMMARY_OUTPUT_TOKENS
    assert relay.payloads[0]["options"]["num_ctx"] == 32768
    operations = list(app.state.agent.store.ops.values())
    assert len(operations) == 1
    assert operations[0].kind == "summary" and operations[0].state == "completed"


async def test_a_second_summary_gets_503_retry_after_without_queuing(monkeypatch):
    release = asyncio.Event()
    relay = SummaryRelay(hold=release)
    app = summary_app(monkeypatch, Counter(), relay)
    runtime = runtime_for(app)
    messages = [Message(MessageRole.USER, "original")]
    first = asyncio.create_task(runtime.summarise("qwen2.5:7b", messages, 32768))
    await relay.started.wait()

    # A busy node must refuse before counting another potentially slow prefix.
    async def unexpected_measure(*args):
        raise AssertionError("busy summary should not count another prefix")

    monkeypatch.setattr(app.state.agent.counter, "measure", unexpected_measure)
    try:
        with pytest.raises(ServerOverloadedError) as caught:
            await runtime.summarise("qwen2.5:7b", messages, 32768)
        assert caught.value.retry_after_seconds == 2
        assert len(app.state.agent.store.ops) == 1
    finally:
        release.set()
        assert await first == "Summary."


@pytest.mark.parametrize("counter", [None, Counter(counted=None), Counter(counted=32768)])
async def test_uncounted_or_over_budget_summary_never_sends(monkeypatch, counter):
    relay = SummaryRelay()
    app = summary_app(monkeypatch, counter, relay)
    with pytest.raises(NoAvailableModelError):
        await runtime_for(app).summarise("qwen2.5:7b", [Message(MessageRole.USER, "x")], 32768)
    assert not relay.payloads
    assert not app.state.agent.store.ops


async def test_summary_body_byte_cap_is_checked_before_counter_or_admission(monkeypatch):
    counter = Counter()
    relay = SummaryRelay()
    app = summary_app(monkeypatch, counter, relay)
    with pytest.raises(NoAvailableModelError):
        await runtime_for(app).summarise(
            "qwen2.5:7b", [Message(MessageRole.USER, "x" * SUMMARY_INPUT_MAX_BYTES)], 32768
        )
    assert not counter.prompts and not relay.payloads and not app.state.agent.store.ops


class CollectSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)

    async def checkpoint(self, observed: Any) -> None:
        pass


@pytest.mark.parametrize(
    "text,output",
    [("x" * (SUMMARY_MAX_BYTES + 1), 5), ("x", 601), ("x", None)],
    ids=["bytes", "tokens", "unavailable"],
)
async def test_summary_output_budget_refuses_after_terminal_evidence(text, output):
    relay = SummaryRelay(text=text)
    sink = CollectSink()
    outcome = await bounded_summary(relay.chat({}), Counter(output=output), "ref")(sink)
    assert isinstance(outcome, RuntimeRefused)
    assert not sink.events


async def test_summary_execution_timeout_is_uncertain_and_blocks_the_node():
    relay = SummaryRelay(hold=asyncio.Event())
    store = MemoryStore()
    dispatcher = Dispatcher(store)
    attempt = await dispatcher.submit(
        "summary",
        "summary",
        bounded_summary(relay.chat({}), Counter(), "ref", timeout_s=0.01),
    )
    outcome = await attempt.settled
    assert isinstance(outcome, Uncertain) and outcome.reason == "summary_deadline"
    assert store.ops["summary"].state == "outcome_unknown"
    assert dispatcher.state.value == "blocked"


async def test_output_count_timeout_after_done_preserves_terminal_evidence():
    class SlowCounter(Counter):
        async def count_parts(self, ref: str, texts: Any) -> list[int] | None:
            await asyncio.Event().wait()

    outcome = await bounded_summary(SummaryRelay().chat({}), SlowCounter(), "ref", timeout_s=0.01)(
        CollectSink()
    )
    assert isinstance(outcome, RuntimeRefused)
    assert outcome.reason == "summary_output_count_deadline"
