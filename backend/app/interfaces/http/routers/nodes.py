"""Compute node management.

The first node write path, and by security.md section 7.2 it ships with the SSRF
guard: `ManageNodes` validates every address against the tailnet range before it
is stored. Authorization is not enforced here; each use case declares and checks
its scope, so a second caller reaching the same use case cannot skip it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.application.use_cases.manage_nodes import ManageNodes
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_manage_nodes
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateNodeRequest,
    NodeResponse,
    UpdateNodeRequest,
)

router = APIRouter(tags=["nodes"])


@router.get("/nodes")
async def list_nodes(
    actor: Annotated[Actor, Depends(current_actor)],
    nodes: Annotated[ManageNodes, Depends(build_manage_nodes)],
) -> list[NodeResponse]:
    return [NodeResponse.of(n) for n in await nodes.list_all(actor)]


@router.get("/nodes/{node_id}")
async def read_node(
    node_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    nodes: Annotated[ManageNodes, Depends(build_manage_nodes)],
) -> NodeResponse:
    return NodeResponse.of(await nodes.get(actor, node_id))


@router.post("/nodes", status_code=201)
async def create_node(
    payload: CreateNodeRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    nodes: Annotated[ManageNodes, Depends(build_manage_nodes)],
) -> NodeResponse:
    node = await nodes.register(
        actor,
        name=payload.name,
        address=payload.address,
        total_memory_gb=payload.total_memory_gb,
        runtimes=frozenset(payload.runtimes),
    )
    return NodeResponse.of(node)


@router.patch("/nodes/{node_id}")
async def update_node(
    node_id: str,
    payload: UpdateNodeRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    nodes: Annotated[ManageNodes, Depends(build_manage_nodes)],
) -> NodeResponse:
    node = await nodes.update(
        actor,
        node_id,
        name=payload.name,
        address=payload.address,
        total_memory_gb=payload.total_memory_gb,
        runtimes=frozenset(payload.runtimes) if payload.runtimes is not None else None,
    )
    return NodeResponse.of(node)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    nodes: Annotated[ManageNodes, Depends(build_manage_nodes)],
) -> Response:
    await nodes.delete(actor, node_id)
    return Response(status_code=204)


@router.post("/nodes/{node_id}/check")
async def check_node_health(
    node_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    nodes: Annotated[ManageNodes, Depends(build_manage_nodes)],
) -> NodeResponse:
    """Probe the node now and return its freshly observed status, for the UI's
    refresh action rather than waiting out the heartbeat interval."""
    return NodeResponse.of(await nodes.check_health(actor, node_id))
