"""Editing what serves each capability.

Without these routes the gateway cannot serve anything: `RouteChatRequest`
reads a policy from the database, and until Phase 1 there was no way to write
one, so every inference request answered "no model is currently available".

The request body is a closed set of structured fields, never an expression
string. These policies are authored here and evaluated inside the gateway
process, so accepting an expression would turn editing a policy into running
code in the gateway. See docs/ARCHITECTURE.md section 2.4.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.application.use_cases.manage_routing_policies import ManageRoutingPolicies
from app.domain.entities.actor import Actor
from app.domain.entities.model import ModelState
from app.domain.entities.node import NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate
from app.infrastructure.di import build_manage_routing_policies
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    RoutingCandidateBody,
    RoutingPolicyResponse,
    SaveRoutingPolicyRequest,
)

router = APIRouter(prefix="/routing-policies", tags=["routing"])


@router.get("")
async def list_policies(
    actor: Annotated[Actor, Depends(current_actor)],
    policies: Annotated[ManageRoutingPolicies, Depends(build_manage_routing_policies)],
) -> list[RoutingPolicyResponse]:
    return [RoutingPolicyResponse.of(p) for p in await policies.list_all(actor)]


@router.get("/{capability}")
async def read_policy(
    capability: str,
    actor: Annotated[Actor, Depends(current_actor)],
    policies: Annotated[ManageRoutingPolicies, Depends(build_manage_routing_policies)],
) -> RoutingPolicyResponse:
    return RoutingPolicyResponse.of(await policies.get(actor, capability))


@router.put("/{capability}")
async def save_policy(
    capability: str,
    payload: SaveRoutingPolicyRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    policies: Annotated[ManageRoutingPolicies, Depends(build_manage_routing_policies)],
) -> RoutingPolicyResponse:
    """PUT rather than POST: a capability has one policy, and writing it twice
    with the same body has to mean the same thing."""
    policy = await policies.save(actor, capability, [_to_candidate(c) for c in payload.candidates])
    return RoutingPolicyResponse.of(policy)


@router.delete("/{capability}", status_code=204)
async def delete_policy(
    capability: str,
    actor: Annotated[Actor, Depends(current_actor)],
    policies: Annotated[ManageRoutingPolicies, Depends(build_manage_routing_policies)],
) -> Response:
    await policies.delete(actor, capability)
    return Response(status_code=204)


def _to_candidate(body: RoutingCandidateBody) -> RoutingCandidate:
    # The enum constructors are the validation. An unknown state or status
    # raises here, at the boundary, rather than being stored as a string that
    # silently matches nothing when routing evaluates it.
    return RoutingCandidate(
        model_alias=body.model_alias,
        priority=body.priority,
        require=Requirement(
            node_status=frozenset(NodeStatus(s) for s in body.require.node_status),
            model_state=frozenset(ModelState(s) for s in body.require.model_state),
            min_free_memory_gb=body.require.min_free_memory_gb,
        ),
    )
