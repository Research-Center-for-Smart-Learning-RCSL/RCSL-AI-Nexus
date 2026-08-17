"""Load a `scripts/model-eval` run into the platform, as a named administrator.

    docker compose exec -T admin-tailnet \\
        python -m app.infrastructure.import_evaluation \\
        --actor <login> --label "2026-08-15 sixteen-task set" \\
        --ran-at 2026-08-15 --harness-ref scripts/model-eval \\
        --caveat "..." < scripts/model-eval/results.jsonl

**It runs inside a container and reads stdin, and both are consequences of
where the data is.** Postgres publishes no host port, so nothing on the Mac can
reach the database directly; and the harness's `results.jsonl` lives in the
repository rather than in any image, so the file has to arrive through the pipe
rather than through a path the container can open.

**It resolves a real administrator rather than acting as the machine.** The
2026-08-16 policy edit was written straight to Postgres for want of an
authenticated path to the control plane from this host, and its own entry calls
that a real gap: the change was validated by nothing and audited by nothing.
The same gap was available here — this module holds an admin database account
and could simply insert three tables' worth of rows. Instead it looks up the
login it is given, builds that person's actor with their real scopes, and goes
through `ManageEvaluations`, so the import is refused if they lack
`model:write` and audited under their name if they do not. What the operator
gives up is being able to import without naming themselves, which is the point.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from app.adapters.audit.postgres_audit import PostgresAudit
from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.repositories import (
    PostgresEvaluationRepository,
    PostgresUserRepository,
)
from app.application.use_cases.manage_evaluations import ManageEvaluations
from app.domain.entities.actor import Actor
from app.domain.entities.evaluation import EvaluationSample, aggregate
from app.infrastructure.config import get_settings
from app.infrastructure.db import (
    dispose_engine,
    get_session_factory,
    init_engine,
    session_scope,
)
from app.shared.clock import SystemClock

logger = logging.getLogger(__name__)


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
    it covers, and averaging the two together instead reproduces the defect the
    re-run existed to remove — `qwen3.6:27b` comes out at 81.9% against its
    real 87.5%, because the run where it scored zero for an `IndentationError`
    is still in the mean.

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

    ordered = list(phases) if phases else list(by_phase)
    superseded: set[str] = set()
    # Walked backwards, so the last phase named keeps every task it covers and
    # each earlier one contributes only the tasks nothing later re-ran.
    kept: list[list[EvaluationSample]] = []
    for phase in reversed(ordered):
        entries = by_phase.get(phase, [])
        kept.append([sample for task, sample in entries if task not in superseded])
        superseded.update(task for task, _ in entries)
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


async def _resolve_actor(login: str) -> Actor:
    """The administrator this import is performed as.

    Unscoped repository, like every other identity lookup in this codebase: the
    tenant is not known until the account is found. The actor's scopes come
    from the role table rather than from anything stored, so an account whose
    role does not carry `model:write` is refused by the use case.
    """
    authz = RoleAuthorization()
    async with session_scope() as session:
        user = await PostgresUserRepository.unscoped(session).get_by_login(login)
    if user is None:
        raise SystemExit(f"no account with login {login!r}")
    return Actor(
        id=user.id,
        display=user.login,
        role=user.role,
        # The importer runs as a person, through the same use case a browser
        # would reach; `local` is what that identity is called everywhere else.
        source="local",
        scopes=authz.scopes_for(user.role.value),
        tenant_id=user.tenant_id,
    )


def _parse_ran_at(value: str) -> datetime:
    """A date or a timestamp, always ending up timezone-aware.

    A naive value would be written to a `timezone=True` column and read back
    with an offset nobody chose, which on a table ordered by this field decides
    which run the screen calls current.
    """
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_engine(settings)
    try:
        # The harness writes every phase into the same file. `pilot` and
        # `full` answer different questions — one calibrates the task set, the
        # other compares candidates — and a repair phase re-runs tasks whose
        # earlier result measured something other than the model. Both are
        # reasons to name the phases rather than take the file whole.
        samples = parse_samples(sys.stdin.readlines(), phases=args.phase)
        if not samples:
            raise SystemExit("no samples on stdin")

        report = aggregate(
            samples,
            run_id=str(uuid.uuid4()),
            label=args.label,
            # The last phase named is the one the run is filed under, since
            # it is the one whose numbers survive superseding.
            phase=args.phase[-1] if args.phase else "full",
            ran_at=_parse_ran_at(args.ran_at),
            harness_ref=args.harness_ref,
            caveats=args.caveat,
            note=args.note,
        )

        actor = await _resolve_actor(args.actor)
        async with session_scope() as session:
            use_case = ManageEvaluations(
                evaluations=PostgresEvaluationRepository(session),
                authz=RoleAuthorization(),
                audit=PostgresAudit(get_session_factory(), SystemClock()),
            )
            stored = await use_case.import_run(actor, report)

        logger.info(
            "imported %s: %s samples, %s model(s), as %s",
            stored.run.label,
            stored.run.sample_count,
            len(stored.models),
            actor.display,
        )
        for model in stored.models:
            logger.info(
                "  %-28s %s scored, %s no result",
                model.model_ref,
                model.scored_samples,
                model.no_result_samples,
            )
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", required=True, help="login of the importing administrator")
    parser.add_argument("--label", required=True, help="how operators will refer to this run")
    parser.add_argument("--ran-at", required=True, help="when it ran (ISO date or timestamp)")
    parser.add_argument("--harness-ref", default="", help="path or commit of the harness")
    parser.add_argument(
        "--phase",
        action="append",
        default=[],
        help=(
            "harness phase to include; repeatable, and a later one supersedes "
            "an earlier one task by task (e.g. --phase full --phase repair)"
        ),
    )
    parser.add_argument("--note", default="", help="a sentence about the run")
    parser.add_argument(
        "--caveat",
        action="append",
        default=[],
        help="what this run does not establish; repeatable",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
