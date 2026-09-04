from __future__ import annotations

import logging
from contextlib import aclosing

import pytest

from app.application.use_cases.route_chat_request import _estimated_tokens
from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
)
from app.domain.exceptions import ContextTooLongError
from tests.unit.streaming_contract_fixtures import (
    ACTOR,
    FakeRuntime,
    _cjk,
    _run,
    build,
)

pytest_plugins = ("tests.unit.streaming_contract_fixtures",)


async def test_an_estimate_that_disagrees_with_the_tokenizer_is_logged(caplog) -> None:
    """Until 2026-08-17 the estimate was visible only when it refused a request.
    An estimator wrong in the safe direction was therefore invisible, and being
    wrong in the safe direction still costs a caller the context they paid for:
    the incident that day was reconstructed by hand from `usage_records`.
    """
    runtime = FakeRuntime(chunks=1, prompt_tokens=100)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 100 actual: 2.0x, past the top of the band.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" in caplog.text
    assert "over-counting" in caplog.text


async def test_the_known_calibration_is_not_reported_as_drift(caplog) -> None:
    """The estimator runs 1.2x-1.6x high on everything this platform serves, so
    a threshold that called 1.2x a deviation would fire on every request and
    measure nothing. 2026-08-17's refusal was at 1.21x and belongs inside the
    band; what was wrong that day was the ceiling, not the calibration."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=165)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 165 actual, i.e. 1.21x.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" not in caplog.text


async def test_the_prose_ratio_the_third_measurement_found_is_inside_the_band(
    caplog,
) -> None:
    """1.61x on English prose, measured 2026-08-18. The band's top was 1.5 until
    then, taken from the 1.47x maximum of the day before, so this ratio sat just
    outside it — and on an `estimate` basis ordinary prose is the common case,
    which would have made this instrument log over-counting on essentially every
    request it saw. Nothing between 1.5 and 1.65 was covered before this test."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=125)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 125 actual, i.e. 1.6x.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" not in caplog.text


async def test_an_under_counting_estimate_is_named_as_such(caplog) -> None:
    """The two directions are not equally bad and the line says which it saw:
    under-counting is what precedes a silent truncation."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=1000)
    use_case, _, _ = build(runtime, context_length=8192)

    with caplog.at_level(logging.INFO):
        # ~200 estimated against 1000 actual: 0.2x, below the band.
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "under-counting" in caplog.text


async def test_a_truncated_prompt_is_not_judged_for_drift(caplog) -> None:
    """`prompt_eval_count` reports what the runtime evaluated, which saturates
    at num_ctx/2. Dividing the estimate by a saturated figure reports a large
    *over*-count for a prompt the estimator in fact under-counted — inverting
    the one direction this signal exists to catch."""
    # 4096 is exactly num_ctx/2 for the 8192-token model, so this is truncated.
    runtime = FakeRuntime(chunks=1, prompt_tokens=4096)
    use_case, _, _ = build(runtime, context_length=8192, max_context_tokens=32768)

    with caplog.at_level(logging.INFO):
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 600)])

    assert "prompt likely truncated" in caplog.text
    assert "outside its measured band" not in caplog.text


async def test_an_estimate_close_enough_to_the_tokenizer_says_nothing(caplog) -> None:
    """It is a heuristic on character widths and is expected to be loose. A line
    on every request would be noise, and noise is not measurement."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=200)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.INFO):
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 120)])

    assert "outside its measured band" not in caplog.text


async def test_the_refusal_says_which_part_of_the_prompt_was_large() -> None:
    """ "Too long" is a fact; the share is the part a caller can act on.

    The three shares have three different remedies, and on 2026-08-17 a refusal
    that carried only the total sent an operator looking at the conversation
    length when one re-read file was most of it.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(
            use_case,
            messages=[
                Message(role=MessageRole.USER, content="short"),
                Message(role=MessageRole.USER, content="word " * 2000),
            ],
        )

    detail = caught.value.detail or ""
    assert "2 messages" in detail
    assert "tool definitions" in detail
    # The one re-read file dominating the conversation is the case this exists
    # for, so the share has to be legible and not merely present.
    assert "% of the whole" in detail


async def test_the_refusal_counts_tool_definitions_as_their_own_share() -> None:
    """A client whose tool list alone fills the ceiling cannot fix it by
    starting a new conversation: the definitions are resent every turn. That is
    only visible if they are attributed separately from the messages."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    no_compact = Actor(
        id=ACTOR.id,
        display=ACTOR.display,
        role=ACTOR.role,
        source=ACTOR.source,
        scopes=ACTOR.scopes,
        compaction_enabled=False,
    )
    with pytest.raises(ContextTooLongError) as caught:
        async with aclosing(
            use_case.execute(
                no_compact,
                "chat",
                [Message(role=MessageRole.USER, content="hello")],
                tools=[
                    ToolDefinition(
                        name=f"tool_{i}",
                        description="d" * 400,
                        parameters={"type": "object", "properties": {}},
                    )
                    for i in range(10)
                ],
            )
        ) as stream:
            async for _ in stream:
                pass

    assert "10 tool definitions" in (caught.value.detail or "")


def test_a_prompt_of_empty_strings_does_not_divide_by_zero() -> None:
    """The share is a percentage of the total, and a request can consist
    entirely of empty content."""
    from app.application.use_cases.route_chat_request import _estimated_composition

    described = _estimated_composition([Message(role=MessageRole.USER, content="")], [])

    assert "% of the whole" not in described


def test_the_caller_facing_message_carries_a_remedy_that_can_work() -> None:
    """The one 413 that had no remedy until 2026-08-17, on the error where
    sending less is the only thing that works. `detail` never leaves the
    process, so this string is the whole of what a caller is told."""
    message = ContextTooLongError().public_message

    assert "Retrying it unchanged cannot succeed" in message
    # "conversation", not "input", would be advice a caller whose tool
    # definitions fill the ceiling cannot act on.
    assert message.startswith("The input is longer")


async def test_a_large_tool_call_argument_counts_towards_the_largest_turn() -> None:
    """An agent writing a file puts the body in `tool_calls[].arguments` and
    leaves `content` empty. Measuring content alone reported that turn as 0% of
    a conversation it was almost all of — the share exists to name exactly that
    payload, so it has to see it."""
    from app.application.use_cases.route_chat_request import _estimated_composition

    described = _estimated_composition(
        [
            Message(role=MessageRole.USER, content="short"),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=(ToolCall(id="c1", name="apply_patch", arguments="x" * 60000),),
            ),
        ],
        [],
    )

    # Content alone made this "largest turn ~2, 0% of the whole".
    assert "99% of the whole" in described


def test_the_estimator_weights_wide_characters_far_above_ascii() -> None:
    """Pinned because the failure mode is a later simplification back to one
    constant, which is what was wrong. The measured spread on 2026-08-14 was
    4.57 characters per token for English against 1.38 for Traditional Chinese,
    so the two classes cannot share a divisor and stay honest for either.
    """
    ascii_estimate = _estimated_tokens("a" * 3000)
    wide_estimate = _estimated_tokens(_cjk(3000))

    assert wide_estimate > ascii_estimate * 2.5
    # And neither may be optimistic enough to reintroduce the old rule, under
    # which 3000 characters of anything counted as 750 tokens.
    assert ascii_estimate > 750


async def test_a_client_spending_its_window_on_tool_definitions_is_told(caplog) -> None:
    """Said before the ceiling refuses, not when it does.

    On 2026-08-17 a client arrived with 286 definitions worth an estimated
    122870 tokens and could not send a four-message conversation. What made that
    diagnosable was the refusal naming the share -- and nothing had named it on
    any of the requests that succeeded first, on that client or on the two
    others connected the same week.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=4096)

    with caplog.at_level(logging.WARNING):
        await _run(
            use_case,
            messages=[Message(role=MessageRole.USER, content="hello")],
            tools=[
                ToolDefinition(
                    name=f"a_tool_with_a_long_enough_name_{i}",
                    description="A description of the sort a real client sends. " * 8,
                    parameters={"type": "object", "properties": {"q": {"type": "string"}}},
                )
                for i in range(12)
            ],
        )

    assert "tool definitions are" in caplog.text
    assert "resent every turn" in caplog.text


async def test_a_small_request_that_is_mostly_tools_says_nothing(caplog) -> None:
    """The share alone would fire on requests nobody needs to hear about: two
    tools and a one-word question is 90% tools and costs nothing. The absolute
    floor is what makes this a signal rather than a per-request footer."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1_000_000)

    with caplog.at_level(logging.WARNING):
        await _run(
            use_case,
            messages=[Message(role=MessageRole.USER, content="hi")],
            tools=[
                ToolDefinition(name="one", description="short", parameters={}),
                ToolDefinition(name="two", description="short", parameters={}),
            ],
        )

    assert "tool definitions are" not in caplog.text
