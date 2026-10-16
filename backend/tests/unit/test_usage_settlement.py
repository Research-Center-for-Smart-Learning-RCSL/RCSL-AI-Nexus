"""The usage row an agent-backed attempt is billed by (design U2, revision 6
on #24): which figure, from which source, and what `completed` means."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.adapters.persistence.repositories import PostgresUsageSettlement
from app.domain.services.usage_settlement import settle_usage

STARTED = datetime(2026, 10, 9, tzinfo=UTC)
COUNTED = {"counted": 9, "basis": "exact_counter"}


def test_runtime_totals_are_raw_even_when_chunks_outnumber_them() -> None:
    """Two chunks, `done` reporting eval_count 1: the runtime's figure, and the
    chunk count stays an observation."""
    usage = settle_usage(
        state="completed",
        terminal={
            "eval_count": 1,
            "prompt_eval_count": 11,
            "observed_chunk_count": 2,
            "total_duration": 2_500_000_000,
        },
        observed=None,
        provenance=COUNTED,
        started_at=STARTED,
        delivered=True,
    )

    assert (usage.tokens, usage.totals_source) == (1, "runtime_final")
    assert (usage.prompt_tokens, usage.prompt_tokens_basis) == (11, "runtime_final")
    assert usage.runtime_completed and usage.completed
    assert usage.latency_ms == 2500 and usage.at == STARTED + timedelta(milliseconds=2500)


def test_no_done_with_a_checkpoint_is_an_estimate_from_chunks() -> None:
    usage = settle_usage(
        state="failed",
        terminal={"resolution": "operator_reset"},
        observed={"observed_chunk_count": 7, "observed_elapsed_ms": 1200},
        provenance=COUNTED,
        started_at=STARTED,
        delivered=None,
    )

    assert (usage.tokens, usage.totals_source) == (7, "estimated_from_chunks")
    assert (usage.prompt_tokens, usage.prompt_tokens_basis) == (9, "exact_counter")
    assert not usage.runtime_completed and not usage.completed
    assert usage.latency_ms == 1200


def test_no_done_and_no_checkpoint_is_unavailable_and_says_so() -> None:
    usage = settle_usage(
        state="failed",
        terminal=None,
        observed=None,
        provenance={"counted": 40, "basis": "estimate"},
        started_at=STARTED,
        delivered=None,
    )

    assert (usage.tokens, usage.totals_source) == (0, "unavailable")
    assert (usage.prompt_tokens, usage.prompt_tokens_basis) == (40, "estimate")
    assert usage.latency_ms == 0


def test_an_absent_delivery_flag_is_never_a_settled_success() -> None:
    for delivered, expected in ((None, False), (False, False), (True, True)):
        usage = settle_usage(
            state="completed",
            terminal={"eval_count": 2},
            observed=None,
            provenance=None,
            started_at=STARTED,
            delivered=delivered,
        )
        assert usage.completed is expected


def test_a_completed_attempt_without_runtime_totals_is_not_called_final() -> None:
    usage = settle_usage(
        state="completed",
        terminal={"observed_chunk_count": 3},
        observed=None,
        provenance=None,
        started_at=STARTED,
        delivered=True,
    )

    assert usage.totals_source == "estimated_from_chunks"
    assert usage.prompt_tokens_basis == "estimate"


def test_the_runtimes_timings_are_whole_milliseconds() -> None:
    """PR7: nanoseconds from `done`, floored, never rounded up into time the
    runtime did not spend."""
    usage = settle_usage(
        state="completed",
        terminal={
            "eval_count": 2,
            "prompt_eval_duration": 28_940_123_456,
            "eval_duration": 999_999,
            "load_duration": 0,
        },
        observed=None,
        provenance=None,
        started_at=STARTED,
        delivered=True,
    )

    assert (usage.prompt_eval_ms, usage.eval_ms, usage.load_ms) == (28940, 0, 0)


def test_timings_the_runtime_did_not_report_are_null_not_zero() -> None:
    for terminal in (None, {"resolution": "operator_reset"}, {"eval_count": 2}):
        usage = settle_usage(
            state="completed" if terminal else "failed",
            terminal=terminal,
            observed={"observed_chunk_count": 3},
            provenance=None,
            started_at=STARTED,
            delivered=None,
        )
        assert (usage.prompt_eval_ms, usage.eval_ms, usage.load_ms) == (None, None, None)


def test_a_malformed_timing_is_null() -> None:
    usage = settle_usage(
        state="completed",
        terminal={"eval_count": 2, "prompt_eval_duration": -1, "eval_duration": "5"},
        observed=None,
        provenance=None,
        started_at=STARTED,
        delivered=True,
    )

    assert (usage.prompt_eval_ms, usage.eval_ms) == (None, None)


class _Session:
    def __init__(self, executed: list[dict[str, Any]]) -> None:
        self._executed = executed

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def begin(self) -> _Session:
        return self

    async def execute(self, _statement: Any, params: dict[str, Any]) -> None:
        self._executed.append(params)


class _Sweep(PostgresUsageSettlement):
    """The sweep's loop, with the database queries replaced."""

    def __init__(self, poison: set[str]) -> None:
        self.reconciled: list[dict[str, Any]] = []
        super().__init__(cast("Any", lambda: _Session(self.reconciled)))
        self.poison = poison
        self.ordered_with: list[set[str]] = []

    async def _candidates(self, limit: int) -> tuple[list[str], list[str]]:
        self.ordered_with.append(set(self._failing))
        return ["bad", "good-1", "good-2"], ["late-1"]

    async def settle(self, op_id: str) -> bool:
        if op_id in self.poison:
            raise RuntimeError("malformed billing snapshot")
        return True


async def test_one_attempt_that_raises_does_not_stall_the_sweep() -> None:
    """Review on #32: the rest are settled, the late delivery reconciled."""
    sweep = _Sweep(poison={"bad"})

    assert await sweep.sweep() == 2
    assert sweep.reconciled == [{"op_id": "late-1"}]


async def test_an_attempt_that_raised_is_ordered_behind_the_rest_until_it_settles() -> None:
    sweep = _Sweep(poison={"bad"})
    await sweep.sweep()
    await sweep.sweep()
    assert sweep.ordered_with == [set(), {"bad"}]

    sweep.poison.clear()
    await sweep.sweep()
    await sweep.sweep()
    assert sweep.ordered_with[-1] == set(), "forgotten once it settles"
