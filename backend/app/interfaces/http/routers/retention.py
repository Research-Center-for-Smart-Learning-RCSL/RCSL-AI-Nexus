"""How long records are kept, and deleting them ahead of that.

Platform-global like tenants, and behind the same kind of scope: every route
here requires `retention:write`, which only `admin` holds. The use case does
the checking, as everywhere else; this module only decides the shape of the
request.

The preview and the purge are separate endpoints on purpose. A single call that
returned a count and deleted would make "show me what this would do" and "do it"
the same request, and the difference between them is the whole point of asking.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.use_cases.manage_retention import ManageRetention
from app.domain.entities.actor import Actor
from app.domain.entities.retention import RetentionDataset
from app.infrastructure.di import build_manage_retention
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    PurgeOutcomeResponse,
    RetentionPolicyResponse,
    RetentionPreviewResponse,
    SetRetentionPolicyRequest,
)

router = APIRouter(prefix="/retention", tags=["retention"])

UseCase = Annotated[ManageRetention, Depends(build_manage_retention)]


@router.get("")
async def list_retention_policies(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> list[RetentionPolicyResponse]:
    """Every dataset, including those still on the default.

    A dataset with no stored row is returned with the default rather than
    omitted, because a screen that listed only configured rows would show
    nothing on a fresh deployment and imply that nothing ever expires.
    """
    return [RetentionPolicyResponse.of(p) for p in await use_case.list_policies(actor)]


@router.get("/{dataset}/preview")
async def preview_purge(
    dataset: RetentionDataset,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
    days: Annotated[int | None, Query()] = None,
) -> RetentionPreviewResponse:
    """How many rows would go, under the stored policy or a proposed one.

    `days` is what lets the form answer "what would saving this do" before it
    is saved. A window that turns out to remove a year of history is worth
    learning about from the form rather than from the result.
    """
    preview = await use_case.preview(actor, dataset, days)
    return RetentionPreviewResponse(
        dataset=preview.dataset.value, days=preview.days, affected=preview.affected
    )


@router.put("/{dataset}")
async def set_retention_policy(
    dataset: RetentionDataset,
    body: SetRetentionPolicyRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
) -> RetentionPolicyResponse:
    policy = await use_case.set_policy(actor, dataset, body.days)
    return RetentionPolicyResponse.of(policy)


@router.post("/{dataset}/purge")
async def purge_dataset(
    dataset: RetentionDataset,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: UseCase,
    days: Annotated[int | None, Query()] = None,
) -> PurgeOutcomeResponse:
    """Delete now rather than waiting for the sweep.

    `days` narrows this one run without changing the policy, which is the
    "clear this specific thing" case: a window tighter than the stored one,
    applied once, leaving the standing rule alone.
    """
    outcome = await use_case.purge(actor, dataset, days)
    return PurgeOutcomeResponse(
        dataset=outcome.dataset.value,
        cutoff=outcome.cutoff,
        deleted=outcome.deleted,
    )
