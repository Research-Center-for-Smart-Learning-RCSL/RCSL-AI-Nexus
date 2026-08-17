"""Reducing evaluation samples to the report a screen renders.

The properties worth pinning are the ones a plausible-looking wrong answer
would satisfy: a mean over the wrong denominator, a verdict computed from one
model instead of the field, a task order sorted alphabetically because that is
what a dict does.

The first case is the published 2026-08-15 reading in miniature. It is built
from samples rather than asserted against remembered numbers, so it tests the
arithmetic rather than restating it — but the shape (three models, a task
nobody passes, a task everybody passes, a task that separates them) is that
run's shape, which is what makes the verdicts meaningful.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.entities.evaluation import (
    DISCRIMINATION_THRESHOLD,
    EvaluationSample,
    TaskVerdict,
    aggregate,
)

RAN_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def sample(
    model: str,
    task: str,
    score: float | None,
    *,
    group: str = "A",
    round_index: int = 0,
    wall: float | None = None,
    gen: float | None = None,
    depth: int | None = None,
) -> EvaluationSample:
    return EvaluationSample(
        model_ref=model,
        task=task,
        group=group,
        round_index=round_index,
        score=score,
        generation_tokens_per_second=gen,
        prompt_tokens=depth,
        wall_seconds=wall,
    )


def report_of(samples: list[EvaluationSample]):
    return aggregate(
        samples,
        run_id="run-1",
        label="a run",
        phase="full",
        ran_at=RAN_AT,
        harness_ref="scripts/model-eval",
    )


def test_a_model_scores_the_mean_of_what_it_answered_not_of_what_it_attempted() -> None:
    """A sample that returned no result lowers the count, never the score.

    The distinction the harness's own report insists on: a candidate that
    produced nothing and one that answered badly are different findings, and
    scoring the first as a zero merges them.
    """
    report = report_of(
        [
            sample("m1", "t1", 1.0),
            sample("m1", "t2", 0.5),
            sample("m1", "t3", None),
        ]
    )

    (model,) = report.models
    assert model.score == pytest.approx(0.75)
    assert model.scored_samples == 2
    assert model.no_result_samples == 1


def test_wall_clock_is_summed_within_a_round_and_reported_as_a_range() -> None:
    """One round is one pass over the whole set, so the figure a reader wants
    is the pass, not the task."""
    report = report_of(
        [
            sample("m1", "t1", 1.0, round_index=0, wall=100.0),
            sample("m1", "t2", 1.0, round_index=0, wall=50.0),
            sample("m1", "t1", 1.0, round_index=1, wall=110.0),
            sample("m1", "t2", 1.0, round_index=1, wall=70.0),
        ]
    )

    (model,) = report.models
    assert model.seconds_per_round_min == pytest.approx(150.0)
    assert model.seconds_per_round_max == pytest.approx(180.0)


def test_the_generation_rate_travels_with_the_prompt_depth_it_was_measured_at() -> None:
    """A rate without a depth cannot be compared with another one — the rule
    the harness states, and the reason two earlier comparisons in this project
    had to be withdrawn."""
    report = report_of(
        [
            sample("m1", "t1", 1.0, gen=60.0, depth=700),
            sample("m1", "t2", 1.0, gen=70.0, depth=728),
        ]
    )

    (model,) = report.models
    assert model.generation_tokens_per_second == pytest.approx(65.0)
    assert model.prompt_depth_tokens == 714


def test_verdicts_are_a_property_of_the_field_not_of_one_model() -> None:
    """The three cases the evaluation's design turns on.

    `everybody` is saturated high and contributes nothing to the comparison;
    `nobody` is saturated low, which is a finding about the task or the whole
    field — the `insufficient_data` case, where all three candidates invented a
    number rather than reporting that the data did not determine one; and
    `separates` is the kind the verdict actually rests on.
    """
    report = report_of(
        [
            sample("m1", "everybody", 1.0),
            sample("m2", "everybody", 1.0),
            sample("m1", "nobody", 0.0),
            sample("m2", "nobody", 0.0),
            sample("m1", "separates", 1.0),
            sample("m2", "separates", 0.5),
            sample("m1", "close", 0.9),
            sample("m2", "close", 0.8),
        ]
    )

    verdicts = report.verdicts()
    assert verdicts["everybody"] is TaskVerdict.SATURATED_HIGH
    assert verdicts["nobody"] is TaskVerdict.SATURATED_LOW
    assert verdicts["separates"] is TaskVerdict.DISCRIMINATES
    # 0.1 apart, under the 0.15 threshold: a real result that does not carry
    # the comparison, which is not the same as carrying it weakly.
    assert verdicts["close"] is TaskVerdict.UNDECIDED


def test_the_threshold_is_a_floor_rather_than_a_strict_gap() -> None:
    report = report_of([sample("m1", "t", 1.0), sample("m2", "t", 0.85)])
    assert report.verdicts()["t"] is TaskVerdict.DISCRIMINATES


def test_task_order_follows_the_task_set_rather_than_the_alphabet() -> None:
    """The harness emits tasks in the order the set is meant to be read, and
    the groups mean something in that order. Sorting here would silently
    reorder every row of the screen."""
    report = report_of(
        [
            sample("m1", "zulu", 1.0, group="A"),
            sample("m1", "alpha", 1.0, group="B"),
            sample("m1", "mike", 1.0, group="C"),
        ]
    )

    assert [entry.task for entry in report.tasks] == ["zulu", "alpha", "mike"]


def test_every_model_gets_a_row_for_every_task_including_the_ones_it_skipped() -> None:
    """A grid with holes in it is a grid whose columns do not line up. A model
    that never attempted a task is present with no score rather than absent,
    so the screen renders a gap instead of shifting a row left."""
    report = report_of([sample("m1", "t1", 1.0), sample("m2", "t2", 1.0)])

    grid = {(entry.model_ref, entry.task): entry for entry in report.tasks}
    assert grid[("m1", "t2")].score is None
    assert grid[("m1", "t2")].samples == 0
    assert grid[("m2", "t1")].score is None


def test_a_task_nobody_scored_has_no_verdict_at_all() -> None:
    """Rather than a verdict computed from an empty list, which would report
    saturation — `all()` is true of nothing — about a task that was never
    measured."""
    report = report_of([sample("m1", "t1", 1.0), sample("m1", "unscored", None)])
    assert "unscored" not in report.verdicts()


def test_a_run_with_no_samples_is_refused() -> None:
    """An import that read the wrong file. Stored, it would put an empty table
    on the screen, indistinguishable from a run where every model failed."""
    with pytest.raises(ValueError, match="at least one sample"):
        report_of([])


def test_the_run_carries_its_caveats_rather_than_the_page_asserting_them() -> None:
    report = aggregate(
        [sample("m1", "t1", 1.0)],
        run_id="run-1",
        label="a run",
        phase="full",
        ran_at=RAN_AT,
        harness_ref="scripts/model-eval",
        caveats=["eleven of eighteen tasks carry no signal"],
        note="a note",
    )
    assert report.run.caveats == ("eleven of eighteen tasks carry no signal",)
    assert report.run.note == "a note"
    assert report.run.sample_count == 1


def test_the_threshold_matches_the_harness_script_it_was_copied_from() -> None:
    """The duplication in `DISCRIMINATION_THRESHOLD` is guarded, not trusted.

    That constant's docstring said this file "pins the two together" from the
    day it was written, and until 2026-08-17 nothing here did: every case above
    is synthetic and none of them had ever read `analyse.py`. A comment
    claiming coverage that does not exist is worse than no comment, because it
    is read as a reason not to look.

    A text check rather than an import, because the script is a developer tool
    outside the application package and has no importable constant -- the value
    is a literal in the comparison. Rewording that comparison fails this test,
    which is correct: it means somebody changed the definition of what it is
    for a task to separate two models, and the platform's copy has to move with
    it or stop agreeing with the report it was derived from.
    """
    analyse = Path(__file__).resolve().parents[3] / "scripts" / "model-eval" / "analyse.py"
    if not analyse.is_file():  # pragma: no cover - the harness travels with the repo
        pytest.skip("scripts/model-eval/analyse.py is not present")

    match = re.search(r"\(max\(got\) - min\(got\)\) >= ([0-9.]+)", analyse.read_text())

    assert match, "analyse.py no longer compares the spread the way this module does"
    assert float(match.group(1)) == DISCRIMINATION_THRESHOLD
