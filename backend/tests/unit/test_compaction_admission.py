"""PR3: compact against the target, then enforce the final admission bound."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.application.use_cases.route_chat_request.compaction import _compact_tool_results
from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import ContextTooLongError, NoAvailableModelError, ServerOverloadedError
from app.domain.services import validated_profiles
from app.node_agent.guard import GuardPass, Registration, check_generation
from app.node_agent.wire import GenerationRequest
from tests.unit.streaming_contract_fixtures import (
    ACTOR,
    FakeCounter,
    FakeRepo,
    FakeRuntime,
    _drain,
    build,
)
from tests.unit.test_validated_widening import PROFILE


class ContentCounter(FakeCounter):
    """Count the transformed content, rather than returning scripted answers."""

    def __init__(self) -> None:
        super().__init__(total=0, declared=32768)

    async def count_prompt(self, ref, messages, tools) -> int:
        self.asked.append(ref)
        return sum(len(message.content) for message in messages) + sum(
            len(tool.description) for tool in tools
        )

    async def measure(self, ref, messages, tools) -> Measurement:
        return Measurement(
            identity="m" * 64,
            counted=await self.count_prompt(ref, messages, tools),
            declared_context=32768,
            encoder="native:e",
            renderer="jinja:r",
        )


@pytest.mark.parametrize(("widened", "description_size"), [(False, 20_000), (True, 33_000)])
async def test_target_overflow_is_compacted_even_below_deployment_cap(
    monkeypatch: pytest.MonkeyPatch, widened: bool, description_size: int
) -> None:
    monkeypatch.setattr(
        validated_profiles, "VALIDATED", (replace(PROFILE, tools=True),) if widened else ()
    )
    runtime = FakeRuntime(chunks=1)
    use_case, usage, _ = build(
        runtime,
        tokens=ContentCounter(),
        context_length=32768,
        ceiling=1024,
        max_context_tokens=122880,
    )
    use_case._nodes = FakeRepo(
        [
            Node(
                id="n1",
                name="n1",
                address="100.64.0.1",
                status=NodeStatus.ONLINE,
                total_memory_gb=64,
                runtime_version="0.33.2",
                runtime_version_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]
    )
    await _drain(
        use_case,
        [Message(role=MessageRole.USER, content="task")],
        thinking=False,
        tools=[ToolDefinition(name="search", description="x" * description_size, parameters={})],
    )
    assert runtime.cleaned_up
    assert usage.records[0].compaction_tier == 0
    assert usage.records[0].tokens_after_compaction == 205


async def test_floor_over_cap_reaches_bounded_compaction() -> None:
    messages = [
        Message(role=MessageRole.TOOL, content="x" * 4000, tool_call_id=f"c{i}") for i in range(10)
    ]
    messages += [Message(role=MessageRole.USER, content="ok") for _ in range(20)]
    use_case, usage, _ = build(
        FakeRuntime(chunks=1),
        tokens=ContentCounter(),
        context_length=32768,
        max_context_tokens=1000,
    )
    await _drain(use_case, messages)
    assert usage.records[0].compaction_tier == 1
    assert usage.records[0].tokens_after_compaction < 1000


async def test_payload_byte_bound_refuses_before_counting_and_routing() -> None:
    counter = ContentCounter()
    use_case, _, _ = build(FakeRuntime(), tokens=counter, compaction_payload_bytes=128)
    with pytest.raises(ContextTooLongError) as caught:
        await _drain(
            use_case,
            [Message(role=MessageRole.USER, content="ok")],
            tools=[
                ToolDefinition(name="nested", description="", parameters={"enum": ["界" * 100]})
            ],
        )
    assert "payload exceeds 128 bytes" in str(caught.value)
    assert counter.asked == []


async def test_compaction_timeout_refuses_with_floor_composition() -> None:
    class BlockingCounter(ContentCounter):
        async def count_prompt(self, ref, messages, tools) -> int:
            if self.asked:
                await asyncio.Future()
            return await super().count_prompt(ref, messages, tools)

    counter = BlockingCounter()
    use_case, _, _ = build(
        FakeRuntime(),
        tokens=counter,
        max_context_tokens=1000,
        context_length=32768,
        compaction_timeout_seconds=0.01,
    )
    history = [Message(role=MessageRole.TOOL, content="x" * 4000) for _ in range(20)]
    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, history)
    assert caught.value.basis == "lower_bound"
    assert "20 messages" in caught.value.composition


async def test_busy_summary_preserves_temporary_refusal() -> None:
    async def busy(messages):
        raise ServerOverloadedError(retry_after_seconds=2)

    use_case, _, _ = build(
        FakeRuntime(),
        tokens=FakeCounter(total=5000),
        max_context_tokens=1000,
        summarise_fn=busy,
    )
    with pytest.raises(ServerOverloadedError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="turn") for _ in range(30)])
    assert caught.value.retry_after_seconds == 2


async def test_unresolved_capacity_refuses_without_generating() -> None:
    runtime = FakeRuntime()
    use_case, _, _ = build(runtime, tokens=FakeCounter(total=100, declared=None))
    with pytest.raises(NoAvailableModelError, match="capacity unresolved"):
        await _drain(use_case, [Message(role=MessageRole.USER, content="hello")])
    assert not runtime.cleaned_up


async def test_estimate_reserves_three_times_input_plus_output() -> None:
    use_case, _, _ = build(
        FakeRuntime(),
        tokens=FakeCounter(total=None, declared=8192),
        ceiling=1000,
        context_length=8192,
    )
    # ASCII estimate is ~3334, below 4096, but 3x plus output exceeds 8191.
    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 10_000)])
    assert caught.value.limit == min(8192 // 2, 8192 - 1 - 1000) // 3
    assert "primary" not in str(caught.value)


@pytest.mark.parametrize("output", [1024, 20_000])
async def test_gateway_and_agent_share_the_estimate_admission_boundary(output: int) -> None:
    use_case, _, _ = build(
        FakeRuntime(),
        tokens=FakeCounter(total=None, declared=32768),
        context_length=32768,
        ceiling=output,
    )
    target = (await use_case._models.list_all())[0]
    limit, _, _ = await use_case._prompt_budget(
        0, "estimate", target, [], [], output, node=None, thinking=False
    )
    registered = Registration(context_length=32768, manifest_digest=None, capabilities=("chat",))
    for estimate in (limit, limit + 1):
        # ASCII contributes exactly n/3; empty tools contribute no overhead.
        messages = (Message(role=MessageRole.USER, content="x" * (estimate * 3)),)
        request = GenerationRequest(
            ref=target.ref,
            messages=messages,
            max_tokens=output,
            thinking=False,
            tools=(),
            tool_choice=None,
            sampling=None,
            context_length=32768,
        )
        measured = Measurement(identity="m", counted=None, declared_context=32768)
        verdict = check_generation(request, registered, measured)
        assert isinstance(verdict, GuardPass) == (estimate <= limit)


def test_tier_one_keeps_the_same_historical_prefix_within_a_block() -> None:
    history = [Message(role=MessageRole.TOOL, content="x" * 1000) for _ in range(30)]
    first, _ = _compact_tool_results(history)
    for extra in range(1, 10):
        appended = history + [Message(role=MessageRole.USER, content="turn") for _ in range(extra)]
        later, _ = _compact_tool_results(appended)
        assert later[: len(history)] == first


async def test_compaction_disabled_keeps_target_refusal() -> None:
    use_case, _, _ = build(FakeRuntime(), tokens=ContentCounter(), context_length=32768)
    with pytest.raises(ContextTooLongError):
        async for _ in use_case.execute(
            replace(ACTOR, compaction_enabled=False),
            "chat",
            [Message(role=MessageRole.USER, content="x" * 20000)],
        ):
            pass
