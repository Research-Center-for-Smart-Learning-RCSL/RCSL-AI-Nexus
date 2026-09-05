"""Reading the harness's JSONL, and the phase rule that decides the numbers.

This file exists because the first import of the 2026-08-15 run produced
`qwen3.6:27b` at 81.9% against its published 87.5%, and the table looked
entirely plausible. The cause was not arithmetic: the harness writes every
phase into one file, three prompts were rewritten and re-run under a `repair`
phase after they were found to be measuring the repository's own formatting,
and taking `full` alone puts the superseded zero back into the mean.

So the rule is tested rather than trusted. A wrong answer here is not an error
anybody sees — it is a screen of confident percentages that disagree with the
record by five points.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.domain.entities.evaluation import aggregate
from app.infrastructure.import_evaluation import parse_samples, parse_task_definitions

RAN_AT_ARGS = {
    "run_id": "r1",
    "label": "l",
    "phase": "full",
    "harness_ref": "h",
}


def line(
    *,
    model: str,
    task: str,
    phase: str,
    score: float | None = 1.0,
    round_index: int = 0,
) -> str:
    return json.dumps(
        {
            "model": model,
            "task": task,
            "group": "A",
            "phase": phase,
            "round": round_index,
            "score": score,
            "gen_tok_s": 10.0,
            "prompt_eval_count": 100,
            "wall_s": 5.0,
        }
    )


def test_a_later_phase_supersedes_an_earlier_one_task_by_task() -> None:
    """The 2026-08-15 shape: one task re-run, the rest of the phase kept."""
    lines = [
        line(model="m1", task="kept", phase="full", score=1.0),
        line(model="m1", task="repaired", phase="full", score=0.0),
        line(model="m1", task="repaired", phase="repair", score=0.8),
    ]

    samples = parse_samples(lines, phases=["full", "repair"])

    scores = {(s.task, s.round_index): s.score for s in samples}
    assert scores[("kept", 0)] == 1.0
    # The zero is gone rather than averaged with the re-run.
    assert scores[("repaired", 0)] == 0.8
    assert len(samples) == 2


def test_the_order_of_the_arguments_decides_which_phase_wins() -> None:
    lines = [
        line(model="m1", task="t", phase="full", score=0.0),
        line(model="m1", task="t", phase="repair", score=1.0),
    ]

    assert parse_samples(lines, phases=["full", "repair"])[0].score == 1.0
    assert parse_samples(lines, phases=["repair", "full"])[0].score == 0.0


def test_a_phase_that_is_not_named_contributes_nothing() -> None:
    """`pilot` calibrates the task set against one model and would drag a
    comparison read towards it."""
    lines = [
        line(model="m1", task="t", phase="full", score=1.0),
        line(model="m1", task="t2", phase="pilot", score=0.0),
    ]

    samples = parse_samples(lines, phases=["full"])

    assert [s.task for s in samples] == ["t"]


def test_naming_no_phase_takes_the_file_whole() -> None:
    """Including phases that cover the same task.

    The first version of this test used two phases with disjoint tasks, so it
    passed while the code was quietly superseding — and the precedence it used
    was dict-insertion order, which is where a block happens to sit in the
    file. A `pilot` run appended after a `full` one would have overridden the
    comparison read with a single-model calibration read, and nothing would
    have said so.
    """
    lines = [
        line(model="m1", task="t", phase="full", score=1.0),
        line(model="m1", task="t", phase="pilot", score=0.0),
        line(model="m1", task="t2", phase="pilot", score=0.5),
    ]

    assert len(parse_samples(lines)) == 3


def test_a_repair_that_re_runs_one_model_keeps_the_others() -> None:
    """Supersession is keyed on the pair, not on the task.

    Keyed on the task alone, a repair phase covering one model would drop the
    other models' samples for that task entirely: superseded out of the earlier
    phase, and absent from the later one. The 2026-08-15 file does not show it
    because that repair re-ran all three tasks for all three candidates.
    """
    lines = [
        line(model="m1", task="t", phase="full", score=0.0),
        line(model="m2", task="t", phase="full", score=0.9),
        line(model="m1", task="t", phase="repair", score=0.8),
    ]

    samples = parse_samples(lines, phases=["full", "repair"])

    scores = {(s.model_ref, s.task): s.score for s in samples}
    assert scores[("m1", "t")] == 0.8, "the re-run replaced the model it covered"
    assert scores[("m2", "t")] == 0.9, "the model it did not cover kept its sample"


def test_a_named_phase_the_file_does_not_have_stops_the_import() -> None:
    """`--phase full --phase repiar` used to import `full` alone -- putting the
    superseded zero straight back into the mean -- and file the run under the
    name that matched nothing. Silent, and five points wrong."""
    lines = [line(model="m1", task="t", phase="full")]

    with pytest.raises(ValueError, match="repiar"):
        parse_samples(lines, phases=["full", "repiar"])


def test_a_partial_last_line_costs_only_itself() -> None:
    """The file is appended to across rounds, so a run interrupted mid-write
    leaves one unparseable line above two hundred good ones."""
    lines = [line(model="m1", task="t", phase="full"), '{"model": "m1", "ta']

    assert len(parse_samples(lines, phases=["full"])) == 1


def test_a_line_that_parses_but_names_nothing_stops_the_import() -> None:
    """Distinct from the case above: this is a shape the importer does not
    understand, and guessing at it would store something nobody measured."""
    with pytest.raises(ValueError, match="no model or task"):
        parse_samples(['{"phase": "full", "score": 1.0}'])


def test_a_null_score_survives_as_a_null_rather_than_a_zero() -> None:
    samples = parse_samples([line(model="m1", task="t", phase="full", score=None)])

    assert samples[0].score is None
    report = aggregate(samples, ran_at=datetime(2026, 8, 15, tzinfo=UTC), caveats=(), **RAN_AT_ARGS)
    assert report.models[0].no_result_samples == 1
    assert report.models[0].score is None


def definition(task: str, *, kind: str = "exact", checks: int = 1) -> dict:
    return {
        "task": task,
        "group": "A",
        "kind": kind,
        "prompt": f"the text of {task}",
        "checks": checks,
    }


def test_only_the_tasks_the_run_asked_are_stored() -> None:
    """The shape of the real file, in miniature.

    `tasks.py --json` emits the whole harness — 34 tasks on 2026-09-03 — and a
    run asks the subset its phases selected, 15 of them for `hard-full`. Keeping
    the other nineteen would caption the screen with questions beside scores
    that do not exist, which a reader takes for tasks the run failed rather than
    tasks it never asked.
    """
    samples = parse_samples(
        [
            line(model="m1", task="asked", phase="full"),
            line(model="m2", task="asked", phase="full"),
            line(model="m1", task="also_asked", phase="full"),
        ]
    )

    definitions = parse_task_definitions(
        json.dumps([definition("asked"), definition("never_asked"), definition("also_asked")]),
        samples=samples,
    )

    assert [d.task for d in definitions] == ["asked", "also_asked"]
    assert definitions[0].prompt == "the text of asked"


def test_a_task_the_file_does_not_cover_is_simply_absent() -> None:
    """Not an error. A run may be imported against a file that predates one of
    its tasks, and refusing the whole import would cost the fourteen questions
    the file does describe to withhold the fifteenth."""
    samples = parse_samples([line(model="m1", task="uncovered", phase="full")])

    assert parse_task_definitions(json.dumps([definition("other")]), samples=samples) == []


def test_a_malformed_definition_stops_the_import() -> None:
    """Fatal where a partial JSONL line is not, and the asymmetry is deliberate:
    that file is appended to across rounds, this one is generated whole by a
    single command, so a shape it does not have is a harness that changed its
    output."""
    samples = parse_samples([line(model="m1", task="t", phase="full")])

    with pytest.raises(ValueError, match="missing checks"):
        parse_task_definitions(
            json.dumps([{"task": "t", "group": "A", "kind": "exact", "prompt": "p"}]),
            samples=samples,
        )
    with pytest.raises(ValueError, match="expected a number"):
        parse_task_definitions(
            json.dumps([definition("t") | {"checks": "eleven"}]), samples=samples
        )
    with pytest.raises(ValueError, match="not JSON"):
        parse_task_definitions("[{", samples=samples)
    with pytest.raises(ValueError, match="expected a list"):
        parse_task_definitions(json.dumps({"task": "t"}), samples=samples)
