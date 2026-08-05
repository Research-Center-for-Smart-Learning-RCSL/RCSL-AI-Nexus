"""Authoring the system prompts a caller may select.

Writing one is authority over what a model is told before it reads anybody's
question, which is why it sits behind its own scope rather than behind
`chat:use`. Reading is in the base scopes: choosing a template is part of
asking a question, so a member who may use the chat has to be able to see what
there is to choose from.

There is no substitution and none is planned here; the reason is in
`domain/entities/prompt_template.py` and it is a security boundary rather than
a simplification.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.prompt_template import MAX_SYSTEM_PROMPT_CHARS, PromptTemplate
from app.domain.exceptions import (
    ModelStateConflictError,
    PromptTemplateNotFoundError,
)
from app.domain.ports.repositories import PromptTemplateRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.shared.clock import Clock

MAX_NAME_CHARS = 128


class ManagePromptTemplates:
    def __init__(
        self,
        templates: PromptTemplateRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
        clock: Clock,
        tenant_id: str,
    ) -> None:
        self._templates = templates
        self._authz = authz
        self._audit = audit
        self._clock = clock
        self._tenant_id = tenant_id

    async def list_all(self, actor: Actor) -> list[PromptTemplate]:
        self._authz.require(actor, Scope.PROMPT_READ)
        return await self._templates.list_all()

    async def get(self, actor: Actor, template_id: str) -> PromptTemplate:
        self._authz.require(actor, Scope.PROMPT_READ)
        return await self._require(template_id)

    async def create(
        self, actor: Actor, *, name: str, description: str, system_prompt: str
    ) -> PromptTemplate:
        self._authz.require(actor, Scope.PROMPT_WRITE)
        name = self._validated_name(name)
        system_prompt = self._validated_prompt(system_prompt)

        if await self._templates.get_by_name(name) is not None:
            # Checked here as well as by the unique index, so the caller gets a
            # 409 naming the collision instead of a constraint violation that
            # surfaces as a 500 at commit, after the response is on its way.
            raise ModelStateConflictError(detail=f"a template named {name!r} already exists")

        template = PromptTemplate(
            id=str(uuid.uuid4()),
            tenant_id=self._tenant_id,
            name=name,
            description=description.strip(),
            system_prompt=system_prompt,
        )
        await self._templates.save(template)
        # Read back for the timestamps, which the database assigns. Returning
        # the entity as constructed sends `created_at: null` for a row that
        # has one — the same mistake `IssueInvitation.create_account` carries a
        # comment about, made again here and caught by looking at the response
        # rather than at the test. The columns are NOT NULL; only the in-memory
        # entity is ever without them.
        template = await self._templates.get(template.id) or template
        await self._audit.record(
            actor, "prompt_template.created", target=template.id, detail={"name": name}
        )
        return template

    async def update(
        self,
        actor: Actor,
        template_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
    ) -> PromptTemplate:
        self._authz.require(actor, Scope.PROMPT_WRITE)
        template = await self._require(template_id)

        if name is not None and name.strip() != template.name:
            name = self._validated_name(name)
            existing = await self._templates.get_by_name(name)
            if existing is not None and existing.id != template.id:
                raise ModelStateConflictError(detail=f"a template named {name!r} already exists")

        updated = replace(
            template,
            name=name.strip() if name is not None else template.name,
            description=description.strip() if description is not None else template.description,
            system_prompt=(
                self._validated_prompt(system_prompt)
                if system_prompt is not None
                else template.system_prompt
            ),
            updated_at=self._clock.now(),
        )
        await self._templates.save(updated)
        # The body is not in the detail. It can be long, `audit_log.detail` has
        # a width, and an over-long value once made `PostgresAudit` lose the
        # row silently (PROGRESS 2026-08-02) — losing the record of a change to
        # what every selecting caller is told would be the worst row to drop.
        await self._audit.record(
            actor,
            "prompt_template.updated",
            target=updated.id,
            detail={"name": updated.name, "prompt_chars": str(len(updated.system_prompt))},
        )
        return updated

    async def delete(self, actor: Actor, template_id: str) -> None:
        self._authz.require(actor, Scope.PROMPT_WRITE)
        template = await self._require(template_id)
        await self._templates.delete(template.id)
        # Deleting one does not break a conversation already under way — the
        # template was copied into that request's messages when it was sent —
        # but the next request naming it is refused rather than served without
        # it. See ApplyPromptTemplate.
        await self._audit.record(
            actor, "prompt_template.deleted", target=template.id, detail={"name": template.name}
        )

    def _validated_name(self, name: str) -> str:
        name = name.strip()
        if not name:
            raise ModelStateConflictError(detail="a template needs a name")
        if len(name) > MAX_NAME_CHARS:
            raise ModelStateConflictError(
                detail=f"a template name is at most {MAX_NAME_CHARS} characters"
            )
        return name

    def _validated_prompt(self, system_prompt: str) -> str:
        system_prompt = system_prompt.strip()
        if not system_prompt:
            # An empty template is worse than none: it is selectable, costs a
            # round trip, and does nothing, so the operator concludes selection
            # is broken rather than that the template is empty.
            raise ModelStateConflictError(detail="a template needs a system prompt")
        if len(system_prompt) > MAX_SYSTEM_PROMPT_CHARS:
            raise ModelStateConflictError(
                detail=(
                    f"a system prompt is at most {MAX_SYSTEM_PROMPT_CHARS} characters; "
                    f"this one is {len(system_prompt)}"
                )
            )
        return system_prompt

    async def _require(self, template_id: str) -> PromptTemplate:
        template = await self._templates.get(template_id)
        if template is None:
            raise PromptTemplateNotFoundError(detail=f"no prompt template {template_id}")
        return template
