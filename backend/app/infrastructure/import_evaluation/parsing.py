"""Evaluation JSONL parsing and validation."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.entities.evaluation import EvaluationSample

logger = logging.getLogger("app.infrastructure.import_evaluation")


def parse_samples(lines: Sequence[str], *, phases: Sequence[str] = ()) -> list[EvaluationSample]:
    """Read the harness's JSONL into domain samples, honouring phase order.

    Unparseable lines are skipped rather than fatal, matching `analyse.py`:
    the file is appended to across rounds and a run interrupted mid-write
    leaves a partial last line, which should not cost the two hundred samples
    above it. A line that parses but names no model or task is a different
    thing — that is a shape this importer does not understand — so it raises.

    **A later phase supersedes an earlier one, task by task.** The harness
    writes every phase into the same file, and they are not alternatives: on
    2026-08-15 three prompts were found to be measuring this repository's own
    formatting rather than a model's capability, and the fix was to rewrite
    them and re-run those three tasks for every candidate under a `repair`
    phase. The published figures are `full` with `repair` replacing the tasks
    it covers. Get that wrong in either direction and the defect the re-run
    existed to remove comes back, because the run where `qwen3.6:27b` scored
    zero for an `IndentationError` is still in the mean: importing `full` alone
    puts it at **81.9%** against its real 87.5%, and concatenating both phases
    without letting the later one win puts it at **83.5%**. Neither is a
    rounding difference, and neither raises.

    So the phases are given in order and the last one wins for any task it
    contains. With no phases named, everything in the file is used, which is
    only right for a file holding one run.

    The filter is applied here, on the raw row, because the domain sample
    deliberately has no phase of its own: a stored run has one phase, and a
    field per sample would invite a run that mixes a calibration read with a
    comparison read and averages them together.
    """
    by_phase: dict[str, list[tuple[str, EvaluationSample]]] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("skipped a line that is not JSON")
            continue
        if not isinstance(row, dict) or "model" not in row or "task" not in row:
            raise ValueError(f"sample carries no model or task: {line[:120]}")
        phase = str(row.get("phase", ""))
        if phases and phase not in phases:
            continue
        by_phase.setdefault(phase, []).append(
            (
                str(row["task"]),
                EvaluationSample(
                    model_ref=str(row["model"]),
                    task=str(row["task"]),
                    group=str(row.get("group", "")),
                    round_index=int(row.get("round", 0)),
                    score=None if row.get("score") is None else float(row["score"]),
                    generation_tokens_per_second=_optional_float(row.get("gen_tok_s")),
                    prompt_tokens=_optional_int(row.get("prompt_eval_count")),
                    wall_seconds=_optional_float(row.get("wall_s")),
                ),
            )
        )

    if not phases:
        # Everything, in file order, with nothing superseded. Superseding here
        # would make precedence a property of where a block happens to sit in
        # the file: a `pilot` run appended after a `full` one would override the
        # comparison read with a single-model calibration read, silently. The
        # rule only means something when a caller has named the order.
        return [sample for entries in by_phase.values() for _, sample in entries]

    missing = [phase for phase in phases if phase not in by_phase]
    if missing:
        # Raised rather than ignored, because the failure is silent and
        # expensive: `--phase full --phase repiar` imported `full` alone, which
        # puts the superseded zero back into the mean, and filed the run under
        # the name that matched nothing.
        raise ValueError(
            f"no samples for phase(s) {', '.join(missing)}; "
            f"the file has {', '.join(sorted(by_phase))}"
        )

    # Keyed on the pair, not on the task. A repair phase may re-run one task for
    # only the model it went wrong for, and keying on the task alone would drop
    # the other models' samples for that task: superseded out of the earlier
    # phase, and absent from the later one.
    superseded: set[tuple[str, str]] = set()
    kept: list[list[EvaluationSample]] = []
    # Walked backwards, so the last phase named keeps everything it covers and
    # each earlier one contributes only what nothing later re-ran.
    for phase in reversed(phases):
        entries = by_phase[phase]
        kept.append(
            [sample for task, sample in entries if (task, sample.model_ref) not in superseded]
        )
        superseded.update((task, sample.model_ref) for task, sample in entries)
    return [sample for block in reversed(kept) for sample in block]


def _optional_float(value: object) -> float | None:
    """`json.loads` hands back `Any` as `object` here, so the numeric shape
    is asserted rather than assumed: a string where a rate was expected is a
    harness that changed its output, and it should stop the import rather
    than reach a `Float` column."""
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"expected a number, got {value!r}")
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"expected a number, got {value!r}")
    return int(value)


def _parse_ran_at(value: str) -> datetime:
    """A date or a timestamp, always ending up timezone-aware.

    A naive value would be written to a `timezone=True` column and read back
    with an offset nobody chose, which on a table ordered by this field decides
    which run the screen calls current.
    """
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
