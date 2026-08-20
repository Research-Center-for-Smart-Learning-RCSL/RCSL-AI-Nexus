from __future__ import annotations

import logging

import pytest

from app.domain.entities.chat import (
    Message,
    MessageRole,
    ToolDefinition,
)
from app.domain.exceptions import ContextTooLongError
from tests.unit.streaming_contract_fixtures import (
    MESSAGES,
    FakeCounter,
    FakeRuntime,
    _drain,
    _stream,
    build,
)

pytest_plugins = ("tests.unit.streaming_contract_fixtures",)


async def test_a_payload_the_estimate_would_refuse_is_admitted_when_it_is_counted() -> None:
    """The refusal of 2026-08-17, in miniature. The estimate ran 1.41x high on
    that client's tool definitions, so a payload inside the ceiling was turned
    away by a figure nobody had checked against a tokeniser."""
    counter = FakeCounter(total=900)
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000, tokens=counter)
    # ~1333 by the character estimate, and 900 by the model that will read it.
    messages = [Message(role=MessageRole.USER, content="x" * 4000)]

    collected = [chunk async for chunk in _stream(use_case, messages)]

    assert collected, "the count admits what the estimate refused"
    assert counter.asked == ["primary:latest"], "counted against the model that would serve it"


async def test_the_bound_before_the_slot_refuses_without_asking_any_model() -> None:
    """It runs before routing, so it has no vocabulary to ask — and therefore
    refuses only what no tokeniser could bring under the ceiling."""
    counter = FakeCounter(total=1)
    use_case, _, limiter = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 80_000)])

    assert caught.value.basis == "lower_bound"
    assert "at least" in (caught.value.detail or "")
    assert counter.asked == [], "no model had been chosen yet"
    assert limiter.available == limiter.limit, "and no slot was taken to say so"


async def test_the_bound_admits_what_only_the_exact_count_can_judge() -> None:
    """A payload between the bound and the ceiling waits for a slot in order to
    be judged by a figure that cannot be wrong about the model. That wait is
    the price of the bound being loose, and it is the price that was chosen."""
    counter = FakeCounter(total=5000)
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 6000)])

    assert caught.value.basis == "tokenizer"
    assert caught.value.estimated == 5000
    assert "estimated tokens" not in (caught.value.detail or "")


async def test_a_counter_that_cannot_say_leaves_the_platform_where_it_was() -> None:
    """MLX targets, a model registered but not pulled, a host with no model
    store: the estimate answers, and the caller is told it is one."""
    counter = FakeCounter(total=None)
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 4000)])

    assert caught.value.basis == "estimate"
    assert "estimated tokens" in (caught.value.detail or "")


async def test_the_per_target_ceiling_judges_the_counted_figure_too() -> None:
    """The check that exists because Ollama truncates rather than refusing. It
    has to judge the same figure the global ceiling did, or the two disagree
    about the same payload."""
    counter = FakeCounter(total=5000)
    use_case, _, _ = build(
        FakeRuntime(chunks=1), max_context_tokens=100_000, context_length=8192, tokens=counter
    )

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="short")])

    assert caught.value.limit == 4096, "num_ctx/2, not the deployment ceiling"
    assert caught.value.basis == "tokenizer"


async def test_the_composition_is_counted_the_same_way_the_refusal_was() -> None:
    """A refusal quoting an exact total beside estimated shares invites
    arithmetic that does not work."""
    counter = FakeCounter(total=5000, parts=[4000])
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 6000)])

    assert counter.parts_asked == 1
    assert "~4000 in 1 messages" in (caught.value.composition or "")


async def test_an_exact_count_is_measured_against_the_runtime_on_every_request(
    caplog,
) -> None:
    """The only instrument that can catch a vocabulary bound to the wrong
    model: the ground truth lives in the runtime, so nothing offline can."""
    counter = FakeCounter(total=4000)
    runtime = FakeRuntime(chunks=1, prompt_tokens=1000)
    use_case, _, _ = build(
        runtime, max_context_tokens=100_000, context_length=100_000, tokens=counter
    )

    with caplog.at_level(logging.INFO):
        await _drain(use_case, MESSAGES)

    assert "exact count disagrees with the runtime by +3000 tokens" in caplog.text


async def test_the_measured_residual_is_not_reported_as_a_disagreement(caplog) -> None:
    """Counted minus actual sat between +2 and +14 across every payload shape
    measured on 2026-08-17, so a window that called those news would fire on
    every request and say nothing."""
    counter = FakeCounter(total=1012)
    runtime = FakeRuntime(chunks=1, prompt_tokens=1000)
    use_case, _, _ = build(
        runtime, max_context_tokens=100_000, context_length=100_000, tokens=counter
    )

    with caplog.at_level(logging.INFO):
        await _drain(use_case, MESSAGES)

    assert "disagrees with the runtime" not in caplog.text


async def test_the_bound_and_its_composition_are_measured_the_same_way() -> None:
    """The pre-slot refusal is the one path with no exact figure to reconcile
    against, so a headline on one basis beside shares on another is a
    contradiction a caller can do the arithmetic on: the bound divides ASCII by
    8.0 and the estimator by 3.0, which is a factor of 2.7."""
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 80_000)])

    error = caught.value
    assert error.basis == "lower_bound"
    parts = int((error.composition or "").split("~")[1].split(" ")[0])
    assert parts <= (error.estimated or 0), "the shares may not exceed the bound they explain"


async def test_a_composition_never_arrives_on_a_different_basis_from_its_total() -> None:
    """`count_prompt` declines for a payload shape the chat template refuses,
    while `count_parts` needs no template and would have answered exactly. Asked
    independently, that produced an estimated total beside tokenised shares."""

    class TemplateRefuses(FakeCounter):
        async def count_prompt(self, ref, messages, tools) -> int | None:
            return None

    counter = TemplateRefuses(total=None, parts=[7])
    use_case, _, _ = build(FakeRuntime(chunks=1), max_context_tokens=1000, tokens=counter)

    with pytest.raises(ContextTooLongError) as caught:
        await _drain(use_case, [Message(role=MessageRole.USER, content="x" * 6000)])

    assert caught.value.basis == "estimate"
    assert counter.parts_asked == 0, "the parts must not be counted exactly for an estimated total"
    assert "~7 in 1 messages" not in (caught.value.composition or "")


async def test_the_tool_share_is_never_more_than_the_whole(caplog) -> None:
    """Dividing an estimated tool figure by an exact total mixes bases that
    differ by the factor this file's own tables record. For the 286-definition
    client of 2026-08-17 it would have read "tool definitions are 141% of this
    prompt", which is not a rounding error but a sentence nobody can act on."""
    tools = [
        ToolDefinition(name="read_record", description="x" * 400, parameters={"a": "b" * 400})
        for _ in range(40)
    ]
    counter = FakeCounter(total=900)
    use_case, _, _ = build(
        FakeRuntime(chunks=1), max_context_tokens=40_000, context_length=200_000, tokens=counter
    )

    with caplog.at_level(logging.WARNING):
        await _drain(use_case, [Message(role=MessageRole.USER, content="hi")], tools=tools)

    lines = [r for r in caplog.records if "tool definitions are about" in r.getMessage()]
    assert lines, "a payload that is almost entirely tool definitions should say so"
    share = float(lines[0].getMessage().split("about ")[1].split("%")[0])
    assert 0 < share <= 100
