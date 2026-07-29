"""The management assistant's wire contract.

Separate from `chat_schemas.py` because the two endpoints answer different
questions. `/admin/chat` is a general chat panel that happens to be served by
the admin API; this is a helper bound to one screen, and its request carries
what the operator is looking at rather than only what they typed.

**The request cannot carry a `system` message.** `AdminChatRequest` accepts one,
which is correct there: that panel is a chat client and the operator is entitled
to steer it. Here the system message is the assistant's own instructions,
assembled server-side from live domain values, and a client able to supply one
could replace the rules it is meant to state. The role is a `Literal` of two
values rather than three, so the request has no field in which an override could
travel — the same reasoning as `ApiKeyResponse` having no field for the digest.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.interfaces.http.schemas.admin_schemas import UpdateApiKeyRequest

AssistSurface = Literal[
    "api_keys.list",
    "api_keys.create",
    "api_keys.edit",
    "api_docs",
    "other",
]
"""Which screen the operator has open.

A closed set rather than free text: it selects which guidance the system prompt
carries, and a caller able to name an arbitrary surface would be writing part of
the prompt. `other` is the honest answer for every screen the assistant has no
specific help for, and it is what the drawer sends by default.
"""


class AssistMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    """No `system`. See the module docstring — this omission is the control."""

    content: str = Field(min_length=1, max_length=8000)


class ApiKeyDraftIn(BaseModel):
    """Whatever the create or edit form currently holds, as typed.

    Deliberately permissive where `CreateApiKeyRequest` is strict, and the
    asymmetry is the point: a form that already validated does not need help.
    The operator asking "why will this not save?" has a draft that fails every
    rule the strict schema enforces, so validating the draft against it would
    refuse to answer exactly the question the assistant exists for.

    Bounded rather than free, though. `extra="forbid"` and the length caps mean
    the block interpolated into the prompt has a known shape and a known
    ceiling, so this cannot become an arbitrary channel for prompt text dressed
    as form state.

    The numeric fields are strings because that is what the form holds: the
    frontend's schema coerces with `z.coerce` at parse time, so before parsing
    (which is when help is wanted) `rate_limit_rpm` is whatever was typed,
    including `""` and `"abc"`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    scopes: Annotated[list[str], Field(max_length=20)] | None = None
    rate_limit_rpm: str | None = Field(default=None, max_length=40)
    quota_tokens_per_day: str | None = Field(default=None, max_length=40)
    allowed_cidrs: Annotated[list[str], Field(max_length=40)] | None = None
    expires_at: str | None = Field(default=None, max_length=60)


class AssistRequest(BaseModel):
    surface: AssistSurface = "other"
    messages: list[AssistMessageIn] = Field(min_length=1, max_length=40)

    draft: ApiKeyDraftIn | None = None
    """Present on the two key forms, absent elsewhere.

    Never the *response* to `POST /api-keys`. `IssuedApiKeyResponse` carries the
    plaintext, which exists in one place and must stay there; this type has no
    field it could arrive in, which is why the frontend context is typed against
    the draft rather than against whatever the dialog happens to hold.
    """

    key_id: str | None = Field(default=None, max_length=64)
    """Which key is being edited, on `api_keys.edit`. Carried so a proposal can
    name its target; it is the public lookup handle and reveals nothing."""


class ProposalOut(BaseModel):
    """A set of field values the operator may apply to the form in front of
    them. It is a suggestion travelling to a form, not an instruction
    travelling to an endpoint: nothing on the server acts on it, and the
    existing dialog performs the write with the existing authorization and the
    existing audit record.

    `fields` is an `UpdateApiKeyRequest` for both actions, and reusing it is
    load-bearing twice over. It is the exact set of settings the platform lets
    anyone edit, with the same bounds `POST` and `PATCH` enforce, so a proposal
    the API would refuse cannot be rendered as a filled-in form. And it has no
    `owner_id`, so the assistant structurally cannot propose issuing a key to
    somebody else — that is an identity decision belonging to the owner picker,
    which is gated on `api_key:write_any`.
    """

    action: Literal["create", "update"]
    key_id: str | None = None
    fields: UpdateApiKeyRequest
    rationale: str = Field(max_length=400)
    """One line, shown on the proposal card. The operator is about to apply
    this to a form, so the reason travels with it rather than being left in the
    prose above, which they may have scrolled past."""
