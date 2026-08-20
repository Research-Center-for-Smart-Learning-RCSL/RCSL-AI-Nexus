"""Admin authentication account schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MeResponse(BaseModel):
    id: str
    auth_mode: str
    login: str
    display_name: str
    role: str
    scopes: list[str] = Field(default_factory=list)
    """What this caller may do, resolved from the role by `AuthorizationPort`.

    Sent so the UI can gate on the permission rather than on the role name. It
    branched on `isAdmin` in forty-five places, which is a question with two
    answers on a platform that now has six roles: `operator` would have been
    shown a read-only fleet it can in fact write, and `auditor` an Invite
    button the server refuses. Not a secret — it is derived from a hardcoded
    table and every entry is documented in security.md §5.2 — and not a
    control either: the server checks the same scopes on every request, and
    §5.2's "UI-level role gating is a usability affordance only" still holds."""

    session_expires_at: datetime | None = None
    """None on the tailnet entrance, which has no session at all."""


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    """Bounded so an unauthenticated caller cannot make the server hash a
    megabyte. The strength check has its own, higher, ceiling."""


class LoginChallengeResponse(BaseModel):
    challenge: str
    """Opaque handle for the second step. Not a session, and carries no
    privilege: it names a user whose password was verified, nothing more."""

    next: str = "totp"


class TotpLoginRequest(BaseModel):
    challenge: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=8)


class RecoveryCodeLoginRequest(BaseModel):
    challenge: str = Field(min_length=1, max_length=256)
    recovery_code: str = Field(min_length=1, max_length=64)


class EnrolmentResponse(BaseModel):
    provisioning_uri: str
    secret: str
    """Shown once, during enrolment, for the case where no camera is
    available. Never returned afterwards by any endpoint."""

    login: str


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=512)
    totp_code: str = Field(min_length=6, max_length=8)


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
    """The only copy that will ever exist."""


class ResetTargetResponse(BaseModel):
    login: str


class ConsumeResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=512)


class BeginTotpRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    """Re-enrolment replaces a bearer credential, so it proves the current
    password first, exactly as a password change does."""


class ConfirmTotpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)
