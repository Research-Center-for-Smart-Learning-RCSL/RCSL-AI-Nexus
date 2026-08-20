from __future__ import annotations

from app.domain.entities.refusal import MAX_FIGURE_CHARS
from app.domain.exceptions import (
    ApiKeyLifetimeError,
    ContextTooLongError,
    QuotaExceededError,
)
from app.interfaces.http.errors import public_details
from tests.unit.refusal_store_fixtures import (
    _refusal,
)

pytest_plugins = ("tests.unit.refusal_store_fixtures",)


def test_the_stored_figures_are_the_ones_the_caller_was_sent() -> None:
    """One function builds both, which is the only way "a row is a copy of your
    own answer" stays true when somebody adds a tenth error that carries one."""
    exc = ContextTooLongError(
        detail="operator-facing, and it stays in this process",
        estimated=140_059,
        limit=122_880,
        composition="~17189 in 4 messages, ~0 in prior tool calls, ~122870 in 286 definitions",
        basis="tokenizer",
    )

    figures = public_details(exc)

    assert figures["estimated"] == 140_059
    assert figures["limit"] == 122_880
    assert figures["basis"] == "tokenizer"
    assert "operator-facing" not in str(figures)


def test_a_wait_a_caller_was_told_to_serve_is_kept_as_a_figure() -> None:
    """It arrives as a header, and a caller reading their refusals a day later
    has no headers. "How long was I told to wait" is the question a 429 in that
    list raises."""
    figures = public_details(QuotaExceededError(retry_after_seconds=3600))

    assert figures["retry_after_seconds"] == 3600


def test_the_figure_that_cost_an_operator_an_evening_is_now_stored() -> None:
    """The 409 whose reason sat in `detail`. `ApiKeyLifetimeError` carries the
    number now, and the store keeps whatever the caller was shown."""
    figures = public_details(ApiKeyLifetimeError(maximum_days=365))

    assert figures == {"maximum_days": 365}


def test_an_over_long_figure_is_cut_and_says_so_rather_than_being_lost() -> None:
    """`audit_log` lost whole rows to a value wider than its column, silently,
    so padding a URL suppressed the record of probing it."""
    long_composition = "x" * (MAX_FIGURE_CHARS + 500)

    cut = _refusal(figures={"composition": long_composition}).truncated()

    assert cut.figures["composition"].endswith("(truncated)")
    assert len(cut.figures["composition"]) < len(long_composition)


def test_a_row_with_no_figures_is_left_alone() -> None:
    refusal = _refusal()
    assert refusal.truncated() is refusal
