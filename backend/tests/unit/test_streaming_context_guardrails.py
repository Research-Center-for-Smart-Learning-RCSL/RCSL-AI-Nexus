from __future__ import annotations

import logging

import pytest

from app.domain.entities.chat import (
    Message,
    MessageRole,
)
from app.domain.entities.model import RuntimeKind
from app.domain.exceptions import ContextTooLongError
from tests.unit.streaming_contract_fixtures import (
    FakeRuntime,
    _cjk,
    _run,
    build,
)

pytest_plugins = ("tests.unit.streaming_contract_fixtures",)


async def test_the_input_ceiling_counts_cjk_at_its_real_density() -> None:
    """The ceiling was applied as a flat four characters per token until
    2026-08-14, which is right for English prose and wrong for everything else.

    Measured against the tokenizer that day: Traditional Chinese runs at 1.38
    characters per token, so 4.0 admitted 2.9x the configured ceiling. That is
    how a Codex session was let past 65,536 tokens on a limit of 65,536 — and
    the runtime, which truncates rather than refuses, would have answered
    without the start of the conversation.
    """
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    # 1500 CJK characters is ~1360 real tokens and was ~375 under the old rule.
    with pytest.raises(ContextTooLongError):
        await _run(use_case, messages=[Message(role=MessageRole.USER, content=_cjk(1500))])


async def test_the_input_ceiling_still_admits_the_prose_it_always_did() -> None:
    """The correction must not pay for CJK by charging English four times over:
    ASCII is weighted separately, so ordinary prose keeps roughly the capacity
    it had."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 500)])


async def test_the_refusal_names_the_unit_it_judged_in() -> None:
    """`characters exceeds the configured limit` against a limit expressed in
    tokens left the reader to guess at the factor between them, and the factor
    was the part that was wrong."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=1000)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(use_case, messages=[Message(role=MessageRole.USER, content=_cjk(4000))])

    assert "estimated tokens" in (caught.value.detail or "")
    assert "1000" in (caught.value.detail or "")


async def test_a_prompt_the_runtime_truncated_is_reported_to_the_operator(caplog) -> None:
    """The backstop for the estimate being wrong in the unsafe direction.

    Ollama evaluates at most `num_ctx / 2` and drops the rest silently, under a
    `done_reason` that a full generation also uses. Nothing downstream can tell
    the two apart, so the caller gets a fluent answer to a conversation the
    model only half read. Reaching that boundary means the estimator
    under-counted, which is an operator's problem rather than a caller's.
    """
    # The fake model's context_length is 8192, so the runtime's own cap is 4096.
    runtime = FakeRuntime(chunks=1, prompt_tokens=4096)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.WARNING):
        await _run(use_case)

    assert "prompt likely truncated" in caplog.text
    assert "num_ctx/2=4096" in caplog.text


async def test_an_ordinary_prompt_says_nothing(caplog) -> None:
    """The warning has to stay rare enough to mean something."""
    runtime = FakeRuntime(chunks=1, prompt_tokens=4095)
    use_case, _, _ = build(runtime)

    with caplog.at_level(logging.WARNING):
        await _run(use_case)

    assert "prompt likely truncated" not in caplog.text


async def test_a_prompt_the_target_would_truncate_is_refused_before_generating() -> None:
    """The global ceiling is one number; the model that serves the request has
    its own, and on 2026-08-17 the two disagreed by 24x.

    `chat` falls back to a smaller model deliberately — a smaller answer beats
    no answer for a person. An answer from a prompt the runtime silently cut in
    half is neither, so the fallback refuses at its own boundary rather than
    inheriting a ceiling sized for the model it is standing in for.
    """
    runtime = FakeRuntime(chunks=1)
    # Admitted by the deployment ceiling, far past what a 8192-token model reads.
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=8192)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])

    assert "4096" in (caught.value.detail or "")


async def test_that_refusal_does_not_name_the_model_to_the_caller() -> None:
    """`NoAvailableModelError` is careful not to disclose the inventory a few
    lines above, and a refusal anyone can provoke by pasting a long file would
    otherwise enumerate it."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=8192)

    with pytest.raises(ContextTooLongError) as caught:
        await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])

    assert "primary" not in (caught.value.detail or "")


async def test_the_target_ceiling_admits_what_the_model_can_actually_read() -> None:
    """The refusal is the model's real boundary, not a margin below it: the
    2026-08-17 incident was a request refused at 82,000 real tokens by a
    ceiling the model would have served."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=8192)

    # ~1000 estimated tokens, comfortably inside num_ctx/2 = 4096.
    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 600)])


async def test_only_ollama_is_held_to_the_half_context_rule() -> None:
    """`num_ctx / 2` is Ollama's behaviour, not a property of runtimes. MLX
    serves its full registered context, so applying the rule there would refuse
    requests it would have answered whole."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(
        runtime, max_context_tokens=32768, context_length=8192, runtime_kind=RuntimeKind.MLX
    )

    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])


async def test_a_model_registered_before_profiles_were_required_is_not_judged() -> None:
    """The column defaults to 0, which is a row written before the profile was
    required rather than a model that can read nothing. `_set_num_ctx` declines
    to send that value for the same reason."""
    runtime = FakeRuntime(chunks=1)
    use_case, _, _ = build(runtime, max_context_tokens=32768, context_length=0)

    await _run(use_case, messages=[Message(role=MessageRole.USER, content="word " * 3000)])
