"""Persistence evaluations boundary."""

from __future__ import annotations

from typing import Protocol

from app.domain.entities.evaluation import EvaluationReport, EvaluationRun


class EvaluationRepositoryPort(Protocol):
    """Stored capability evaluations.

    Platform-global, like models and nodes: an evaluation describes the fleet
    rather than anyone's content, so there is no tenant to scope by.

    Reads return a whole `EvaluationReport` rather than the three tables it is
    assembled from. The task verdicts are a property of the set of models in a
    run, so a caller holding two of the three lists could compute one that is
    quietly wrong -- assembling in the adapter, once, is what stops that being
    possible at all.
    """

    async def list_runs(self) -> list[EvaluationRun]:
        """Every run, newest first. Carries no scores: the index is a list of
        what has been measured, and a page of it should not read three tables
        for figures nobody has asked for yet."""
        ...

    async def get_report(self, run_id: str) -> EvaluationReport | None: ...

    async def latest_report(self) -> EvaluationReport | None:
        """The most recent run by `ran_at`, which is what the screen opens on.

        By when it ran rather than when it was imported: a run loaded late is
        still an older reading, and ordering by import would let a backfill
        present itself as the current state of the fleet.
        """
        ...

    async def save_report(self, report: EvaluationReport) -> None:
        """Store a run, replacing any run carrying the same label.

        Replacement rather than a second row, because a corrected re-import is
        the expected case: the published 2026-08-15 figures are themselves a
        correction of that day's first reading.

        The report's task definitions are stored with it, and an empty tuple
        stores nothing rather than raising: two runs predate the field, and an
        implementation that treated their absence as a defect would refuse to
        round-trip what is already in the table.
        """
        ...

    async def delete_run(self, run_id: str) -> bool:
        """True when a run was deleted, False when there was none to delete."""
        ...
