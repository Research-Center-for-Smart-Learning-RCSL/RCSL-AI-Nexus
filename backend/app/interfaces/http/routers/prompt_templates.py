"""Prompt template management.

Authorization is not enforced here. `ManagePromptTemplates` declares the scope
each method requires and checks it, so a second caller reaching the same use
case cannot skip the check by not knowing about it. See
docs/architecture/backend.md section 7.

Reading is `prompt:read`, which every account holds, because choosing a
template is part of asking a question. Writing is `prompt:write`, which is
authority over what a model is told before it reads anybody's question.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.application.use_cases.manage_prompt_templates import ManagePromptTemplates
from app.domain.entities.actor import Actor
from app.infrastructure.di import build_manage_prompt_templates
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreatePromptTemplateRequest,
    PromptTemplateResponse,
    UpdatePromptTemplateRequest,
)

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])

TemplatesDep = Annotated[ManagePromptTemplates, Depends(build_manage_prompt_templates)]


@router.get("")
async def list_templates(
    actor: Annotated[Actor, Depends(current_actor)],
    templates: TemplatesDep,
) -> list[PromptTemplateResponse]:
    return [PromptTemplateResponse.of(t) for t in await templates.list_all(actor)]


@router.get("/{template_id}")
async def read_template(
    template_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    templates: TemplatesDep,
) -> PromptTemplateResponse:
    return PromptTemplateResponse.of(await templates.get(actor, template_id))


@router.post("", status_code=201)
async def create_template(
    payload: CreatePromptTemplateRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    templates: TemplatesDep,
) -> PromptTemplateResponse:
    template = await templates.create(
        actor,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
    )
    return PromptTemplateResponse.of(template)


@router.patch("/{template_id}")
async def update_template(
    template_id: str,
    payload: UpdatePromptTemplateRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    templates: TemplatesDep,
) -> PromptTemplateResponse:
    """`PATCH`, so an edit to the description does not require resending the
    body. Every field is optional and only the ones present are written."""
    template = await templates.update(
        actor,
        template_id,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
    )
    return PromptTemplateResponse.of(template)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    templates: TemplatesDep,
) -> Response:
    """A conversation already sent is unaffected — the template was copied into
    that request's messages. The next request naming it is refused with a 404
    rather than served without it."""
    await templates.delete(actor, template_id)
    return Response(status_code=204)
