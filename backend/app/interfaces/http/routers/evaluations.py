"""Stored capability evaluations: what the task set measured, and loading one.

Platform-global like models and nodes, and behind the same scopes — reading
takes `model:read`, importing and deleting take `model:write`. The argument for
reusing them rather than minting a pair is in `ManageEvaluations`.

Mounted on the admin entrances only. The gateway serves callers holding API
keys, and an API key can never hold a control-plane scope (`_SERVICE_SCOPES`),
so the route would exist there only to refuse everyone who could reach it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.application.use_cases.manage_evaluations import ManageEvaluations
from app.domain.entities.actor import Actor
from app.domain.entities.evaluation import EvaluationSample
from app.infrastructure.di import build_manage_evaluations
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    EvaluationReportResponse,
    EvaluationRunResponse,
    ImportEvaluationRequest,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

UseCase = Annotated[ManageEvaluations, Depends(build_manage_evaluations)]


@router.get("")
async def list_evaluation_runs(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> list[EvaluationRunResponse]:
    """Every stored run, newest first, without its scores."""
    return [EvaluationRunResponse.of(run) for run in await use_case.list_runs(actor)]


@router.get("/latest")
async def latest_evaluation(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> EvaluationReportResponse | None:
    """The newest run, or null on a deployment that has never run the set.

    Null rather than a 404, and declared above `/{run_id}` so that `latest` is
    not read as an id. A deployment with no evaluation is in a normal state —
    running the task set is an afternoon's work nobody owes anyone — and a 404
    would have the screen report that as a failure.
    """
    report = await use_case.latest(actor)
    return EvaluationReportResponse.of(report) if report else None


@router.get("/{run_id}")
async def get_evaluation(
    run_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> EvaluationReportResponse:
    return EvaluationReportResponse.of(await use_case.report(actor, run_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def import_evaluation(
    body: ImportEvaluationRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> EvaluationReportResponse:
    """Load a run from its samples, replacing any run with the same label.

    This maps the body and nothing else. The aggregation used to happen here,
    which put a caller-sized calculation *in front of* the use case's scope
    check -- so an account holding no evaluation scope at all could still spend
    the process's CPU on a request it was always going to be refused. The
    samples now travel in and the use case reduces them after refusing.
    """
    return EvaluationReportResponse.of(
        await use_case.import_run(
            actor,
            [
                EvaluationSample(
                    model_ref=sample.model_ref,
                    task=sample.task,
                    group=sample.group,
                    round_index=sample.round_index,
                    score=sample.score,
                    generation_tokens_per_second=sample.generation_tokens_per_second,
                    prompt_tokens=sample.prompt_tokens,
                    wall_seconds=sample.wall_seconds,
                )
                for sample in body.samples
            ],
            label=body.label,
            phase=body.phase,
            ran_at=body.ran_at,
            harness_ref=body.harness_ref,
            caveats=body.caveats,
            note=body.note,
        )
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evaluation(
    run_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> None:
    await use_case.delete_run(actor, run_id)
