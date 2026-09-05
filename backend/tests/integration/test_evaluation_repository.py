"""Evaluation runs against a real Postgres.

Three things the unit tests cannot reach, and each has already been a defect
somewhere in this schema: a JSON column that comes back as something other than
a list of strings, an ordering that holds in a dict and not in a query, and a
delete that leaves orphans behind because the cascade was declared in the ORM
and never made it into the migration.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import PostgresEvaluationRepository
from app.adapters.persistence.sqlalchemy_models import (
    EvaluationModelScoreRow,
    EvaluationTaskDefinitionRow,
    EvaluationTaskScoreRow,
)
from app.domain.entities.evaluation import (
    EvaluationSample,
    EvaluationTaskDefinition,
    aggregate,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
async def session(database_url):
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _report(
    label: str,
    *,
    ran_at: datetime | None = None,
    scores: dict[str, dict[str, float | None]] | None = None,
    caveats: tuple[str, ...] = (),
    definitions: tuple[EvaluationTaskDefinition, ...] = (),
):
    """A report over `{model: {task: score}}`, in the task order given."""
    scores = scores or {"m1": {"zulu": 1.0, "alpha": 0.5}}
    samples = [
        EvaluationSample(
            model_ref=model,
            task=task,
            group="A",
            round_index=0,
            score=score,
            generation_tokens_per_second=60.0,
            prompt_tokens=700,
            wall_seconds=120.0,
        )
        for model, tasks in scores.items()
        for task, score in tasks.items()
    ]
    report = aggregate(
        samples,
        run_id=str(uuid.uuid4()),
        label=label,
        phase="full",
        ran_at=ran_at or datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        harness_ref="scripts/model-eval",
        caveats=caveats,
    )
    return replace(report, task_definitions=definitions)


async def test_a_report_survives_the_round_trip(session) -> None:
    repository = PostgresEvaluationRepository(session)
    stored = _report("round trip", caveats=("eleven of eighteen carry no signal",))
    await repository.save_report(stored)

    read = await repository.get_report(stored.run.id)

    assert read is not None
    assert read.run.label == "round trip"
    # The JSON column, which is the one that can come back as something else.
    assert read.run.caveats == ("eleven of eighteen carry no signal",)
    assert read.models[0].generation_tokens_per_second == pytest.approx(60.0)
    assert read.models[0].prompt_depth_tokens == 700


async def test_task_order_survives_the_query(session) -> None:
    """Held by the id the writer assigns, because the harness's order is the
    order the task set is meant to be read in. A query with no `order_by` at
    all returns rows in whatever order Postgres finds convenient."""
    repository = PostgresEvaluationRepository(session)
    stored = _report("ordering", scores={"m1": {"zulu": 1.0, "alpha": 1.0, "mike": 1.0}})
    await repository.save_report(stored)

    read = await repository.get_report(stored.run.id)

    assert read is not None
    assert [entry.task for entry in read.tasks] == ["zulu", "alpha", "mike"]


async def test_task_text_round_trips_and_keeps_the_order_it_was_written_in(session) -> None:
    """Held by the id the writer assigns, like the task scores: the harness
    emits tasks in the order the set is meant to be read, and a dialogue prompt
    is long enough that a reordered list is not obvious on the screen."""
    repository = PostgresEvaluationRepository(session)
    stored = _report(
        "with text",
        scores={"m1": {"zulu": 1.0, "alpha": 1.0}},
        definitions=(
            EvaluationTaskDefinition(
                task="zulu", group="H", kind="dialogue", prompt="[system prompt]\nbe firm", checks=6
            ),
            EvaluationTaskDefinition(
                task="alpha", group="A", kind="exact", prompt="what is 2 + 2?", checks=1
            ),
        ),
    )
    await repository.save_report(stored)

    read = await repository.get_report(stored.run.id)

    assert read is not None
    assert [d.task for d in read.task_definitions] == ["zulu", "alpha"]
    assert read.task_definitions[0].prompt == "[system prompt]\nbe firm"
    assert read.task_definitions[0].kind == "dialogue"
    assert read.task_definitions[0].checks == 6
    # `task_group` in the column, `group` in the entity: the mapping is the
    # thing that can silently be wired to the wrong one.
    assert read.task_definitions[1].group == "A"


async def test_a_run_stored_without_task_text_still_reads(session) -> None:
    """Two runs predate the field, and a report that could not be read back
    without definitions would be a schema change presented as a feature."""
    repository = PostgresEvaluationRepository(session)
    stored = _report("no text")
    await repository.save_report(stored)

    read = await repository.get_report(stored.run.id)

    assert read is not None
    assert read.task_definitions == ()
    assert read.models[0].score is not None


async def test_deleting_a_run_takes_its_task_text_with_it(session) -> None:
    """The cascade again, on the new table: declared in the ORM alone it passes
    against `create_all` and leaves orphaned prompts in production."""
    repository = PostgresEvaluationRepository(session)
    stored = _report(
        "text to delete",
        definitions=(
            EvaluationTaskDefinition(task="zulu", group="A", kind="exact", prompt="p", checks=1),
        ),
    )
    await repository.save_report(stored)
    assert await _definition_count(session, stored.run.id) == 1

    assert await repository.delete_run(stored.run.id) is True

    assert await _definition_count(session, stored.run.id) == 0


async def test_re_importing_a_label_replaces_the_run_rather_than_adding_one(
    session,
) -> None:
    """The published 2026-08-15 figures are themselves a correction of that
    day's first reading, so this is the expected path and not a corner."""
    repository = PostgresEvaluationRepository(session)
    first = _report("same label", scores={"m1": {"t1": 0.2}})
    await repository.save_report(first)
    second = _report("same label", scores={"m1": {"t1": 0.9}})
    await repository.save_report(second)

    runs = await repository.list_runs()
    assert [run.label for run in runs].count("same label") == 1
    read = await repository.get_report(second.run.id)
    assert read is not None
    assert read.models[0].score == pytest.approx(0.9)
    # And the superseded run's children went with it, rather than staying
    # attached to an id nothing lists.
    assert await repository.get_report(first.run.id) is None
    assert await _child_count(session, first.run.id) == (0, 0)


async def test_deleting_a_run_takes_its_scores_with_it(session) -> None:
    """The cascade is declared in the migration as well as the ORM. Declared in
    only one of the two, this passes against `create_all` and leaves orphans in
    production."""
    repository = PostgresEvaluationRepository(session)
    stored = _report("to delete")
    await repository.save_report(stored)
    assert await _child_count(session, stored.run.id) != (0, 0)

    assert await repository.delete_run(stored.run.id) is True

    assert await repository.get_report(stored.run.id) is None
    assert await _child_count(session, stored.run.id) == (0, 0)


async def test_deleting_a_run_that_is_not_there_reports_it(session) -> None:
    repository = PostgresEvaluationRepository(session)
    assert await repository.delete_run(str(uuid.uuid4())) is False


async def test_latest_is_by_when_it_ran_not_by_when_it_was_loaded(session) -> None:
    """A run imported late is still an older reading. Ordering by import would
    let a backfill present itself as the current state of the fleet."""
    repository = PostgresEvaluationRepository(session)
    newer = _report("newer", ran_at=datetime(2026, 8, 15, tzinfo=UTC))
    older = _report("older", ran_at=datetime(2026, 7, 1, tzinfo=UTC))
    await repository.save_report(newer)
    await repository.save_report(older)  # loaded second, ran first

    latest = await repository.latest_report()

    assert latest is not None
    assert latest.run.label == "newer"


async def _child_count(session, run_id: str) -> tuple[int, int]:
    models = await session.scalar(
        select(func.count())
        .select_from(EvaluationModelScoreRow)
        .where(EvaluationModelScoreRow.run_id == run_id)
    )
    tasks = await session.scalar(
        select(func.count())
        .select_from(EvaluationTaskScoreRow)
        .where(EvaluationTaskScoreRow.run_id == run_id)
    )
    return models or 0, tasks or 0


async def _definition_count(session, run_id: str) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(EvaluationTaskDefinitionRow)
        .where(EvaluationTaskDefinitionRow.run_id == run_id)
    )
    return count or 0
