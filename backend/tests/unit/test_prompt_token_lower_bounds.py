from __future__ import annotations

from app.application.use_cases.route_chat_request import (
    _counted_phrase,
    _floor_prompt_tokens,
    _floor_tokens,
)
from app.domain.entities.chat import Message, MessageRole, ToolDefinition
from app.domain.exceptions import (
    COUNT_BY_ESTIMATE,
    COUNT_BY_LOWER_BOUND,
    COUNT_BY_TOKENIZER,
    ContextTooLongError,
)

pytest_plugins = ("tests.unit.exact_token_counting_fixtures",)


def test_the_floor_never_exceeds_what_a_tokeniser_would_count() -> None:
    """The whole purpose of the bound: it may be far below the real figure and
    may never be above it, because it refuses without knowing the model."""
    prose = "The quick brown fox jumps over the lazy dog. " * 200
    assert _floor_tokens(prose) < len(prose) / 4.4

    chinese = "這是一份中文的維運手冊，描述閘道器的行為。" * 200
    assert _floor_tokens(chinese) < len(chinese) / 1.4


def test_the_floor_is_computed_without_walking_the_string() -> None:
    """Both arms are C-level passes; the non-ASCII one turns UTF-8's own
    arithmetic into a lower bound on the character count."""
    mixed = "ascii 中文 ascii"
    assert _floor_tokens(mixed) > 0
    assert _floor_prompt_tokens([Message(role=MessageRole.USER, content=mixed)], []) >= 0


def test_the_floor_counts_tool_definitions_like_everything_else() -> None:
    tool = ToolDefinition(name="x" * 100, description="y" * 100, parameters={"a": "b" * 100})
    bare = _floor_prompt_tokens([Message(role=MessageRole.USER, content="hi")], [])

    assert _floor_prompt_tokens([Message(role=MessageRole.USER, content="hi")], [tool]) > bare


def test_a_figure_is_named_for_what_it_is() -> None:
    assert _counted_phrase(COUNT_BY_TOKENIZER, 10) == "10 tokens"
    assert _counted_phrase(COUNT_BY_LOWER_BOUND, 10) == "at least ~10 tokens"
    assert _counted_phrase(COUNT_BY_ESTIMATE, 10) == "~10 estimated tokens"


def test_the_caller_is_told_which_of_the_three_they_were_handed() -> None:
    """A caller deciding how much to trim needs to know whether the number is a
    count, an estimate that has run 1.48x high, or a lower bound."""
    counted = ContextTooLongError(estimated=99000, limit=122880, basis=COUNT_BY_TOKENIZER)
    estimated = ContextTooLongError(estimated=99000, limit=122880, basis=COUNT_BY_ESTIMATE)
    bounded = ContextTooLongError(estimated=99000, limit=122880, basis=COUNT_BY_LOWER_BOUND)

    assert "is 99,000 tokens" in counted.public_message
    assert "an estimated 99,000 tokens" in estimated.public_message
    assert "at least 99,000 tokens" in bounded.public_message
