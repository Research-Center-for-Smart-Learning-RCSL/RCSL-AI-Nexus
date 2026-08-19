"""Admin prompt templates schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.application.use_cases.manage_prompt_templates import MAX_NAME_CHARS
from app.domain.entities.prompt_template import (
    MAX_SYSTEM_PROMPT_CHARS,
    PromptTemplate,
)


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    system_prompt: str
    """Returned in full, unlike a key's plaintext or a document's bytes.

    It is not a secret: every member of the tenant may read it (`prompt:read`
    is a base scope), because choosing between templates without being able to
    see what they say is choosing blind. It is also what the operator has to
    read in order to edit it."""

    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def of(cls, template: PromptTemplate) -> PromptTemplateResponse:
        return cls(
            id=template.id,
            name=template.name,
            description=template.description,
            system_prompt=template.system_prompt,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


class CreatePromptTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    description: str = Field(default="", max_length=1024)
    system_prompt: str = Field(min_length=1, max_length=MAX_SYSTEM_PROMPT_CHARS)
    """The ceiling is imported from the domain rather than restated, so the
    form's limit and the rule it enforces cannot drift apart — the same
    arrangement `SetDebugWindowRequest` uses."""


class UpdatePromptTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_CHARS)
    description: str | None = Field(default=None, max_length=1024)
    system_prompt: str | None = Field(
        default=None, min_length=1, max_length=MAX_SYSTEM_PROMPT_CHARS
    )
