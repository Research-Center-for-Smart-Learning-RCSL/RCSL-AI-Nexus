"""The model registry, downloads, and the node listing it needs.

Authorization is not enforced in this file. Each use case declares the scope
it requires and checks it, so a second caller reaching the same use case from
somewhere else cannot skip the check by not knowing about it.
See docs/architecture/backend.md section 7.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.application.use_cases.download_model import DownloadModel
from app.application.use_cases.manage_models import ManageModels
from app.domain.entities.actor import Actor
from app.domain.entities.model import ResourceProfile
from app.infrastructure.di import (
    build_download_model,
    build_manage_models,
)
from app.infrastructure.jobs import schedule_download
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateModelRequest,
    DownloadJobResponse,
    ModelResponse,
    UpdateModelRequest,
)

router = APIRouter(tags=["models"])


@router.get("/models")
async def list_models(
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> list[ModelResponse]:
    return [ModelResponse.of(m) for m in await models.list_all(actor)]


@router.get("/models/{model_id}")
async def read_model(
    model_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> ModelResponse:
    return ModelResponse.of(await models.get(actor, model_id))


@router.post("/models", status_code=201)
async def create_model(
    payload: CreateModelRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> ModelResponse:
    model = await models.register(
        actor,
        alias=payload.alias,
        ref=payload.ref,
        runtime=payload.runtime,
        node_id=payload.node_id,
        capabilities=frozenset(payload.capabilities),
        resource_profile=ResourceProfile(
            memory_gb=payload.resource_profile.memory_gb,
            context_length=payload.resource_profile.context_length,
        ),
    )
    return ModelResponse.of(model)


@router.patch("/models/{model_id}")
async def update_model(
    model_id: str,
    payload: UpdateModelRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> ModelResponse:
    profile = (
        ResourceProfile(
            memory_gb=payload.resource_profile.memory_gb,
            context_length=payload.resource_profile.context_length,
        )
        if payload.resource_profile is not None
        else None
    )
    model = await models.update(
        actor,
        model_id,
        alias=payload.alias,
        ref=payload.ref,
        runtime=payload.runtime,
        node_id=payload.node_id,
        capabilities=frozenset(payload.capabilities) if payload.capabilities else None,
        resource_profile=profile,
    )
    return ModelResponse.of(model)


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> Response:
    await models.delete(actor, model_id)
    return Response(status_code=204)


@router.post("/models/{model_id}/load")
async def load_model(
    model_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> ModelResponse:
    """Refused when the node's memory budget would be exceeded, rather than
    warned about: on unified memory an over-commit drives the machine into
    swap and takes every other model down with it."""
    return ModelResponse.of(await models.load(actor, model_id))


@router.post("/models/{model_id}/unload")
async def unload_model(
    model_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    models: Annotated[ManageModels, Depends(build_manage_models)],
) -> ModelResponse:
    return ModelResponse.of(await models.unload(actor, model_id))


@router.post("/models/{model_id}/download", status_code=202)
async def start_download(
    model_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    downloads: Annotated[DownloadModel, Depends(build_download_model)],
) -> DownloadJobResponse:
    """202, not 201: the work has been accepted and is nowhere near finished.

    `start` claims the model before the task is scheduled, so a second click
    is refused by the state check rather than starting a second pull of the
    same weights.
    """
    status = await downloads.start(actor, model_id)
    schedule_download(request.app, model_id=model_id, job_id=status.job_id)
    return DownloadJobResponse.of(status)


@router.get("/download-jobs/{job_id}")
async def read_download_job(
    job_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    downloads: Annotated[DownloadModel, Depends(build_download_model)],
) -> DownloadJobResponse:
    return DownloadJobResponse.of(await downloads.status(actor, job_id))


# `GET /nodes` moved to routers/nodes.py, which now carries the full node
# lifecycle: the read the model form needs plus the writes that ship with the
# SSRF guard (security.md §7.2).
