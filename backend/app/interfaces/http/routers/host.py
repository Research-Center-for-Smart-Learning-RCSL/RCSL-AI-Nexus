"""The compute host's own free memory and disk.

Its own path rather than `/nodes/host`. That would sit next to
`/nodes/{node_id}` and be matched correctly only because of declaration order,
which is a property nobody checks when reordering a file. This is also not a
node in the registry's sense: it is the machine the runtimes run on, reported by
an agent rather than a row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.use_cases.read_host_status import ReadHostStatus
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_read_host_status
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import HostStatusResponse

router = APIRouter(prefix="/host", tags=["host"])


@router.get("")
async def read_host_status(
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: Annotated[ReadHostStatus, Depends(build_read_host_status)],
) -> HostStatusResponse:
    """200 with `reporting: false` when the agent is absent, not a 503.

    A deployment that never installed the launchd job is in an ordinary state,
    and an error status would put a red mark on a dashboard for a decision
    somebody made on purpose.
    """
    status = await use_case.execute(actor)
    return HostStatusResponse.of(status)
