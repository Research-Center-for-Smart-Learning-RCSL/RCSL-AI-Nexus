"""Request and response shapes for the admin API.

These mirror the zod schemas under frontend/src/features. The frontend parses
every response rather than casting it, so a field renamed here surfaces as a
parse failure on the next call rather than as `undefined` three components
later.

**Nothing here carries a credential outward.** `password_hash` and
`totp_secret` have no representation: the UI learns only whether they are set.
The three values that are returned once and never again — an invitation URL,
a TOTP secret, a set of recovery codes — are marked as such where they appear.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.entities.actor import Role
from app.domain.entities.invitation import Invitation
from app.domain.entities.user import User


class MeResponse(BaseModel):
    id: str
    auth_mode: str
    login: str
    display_name: str
    role: str
    session_expires_at: datetime | None = None
    """None on the tailnet entrance, which has no session at all."""


class UserResponse(BaseModel):
    id: str
    login: str
    display_name: str
    tailscale_login: str | None
    has_local_credentials: bool
    has_totp: bool
    role: str
    debug_logging_until: datetime | None
    created_at: datetime | None

    @classmethod
    def of(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            login=user.login,
            display_name=user.display_name,
            tailscale_login=user.tailscale_login,
            # Derived, never the hash itself.
            has_local_credentials=user.password_hash is not None,
            has_totp=user.totp_secret is not None,
            role=user.role.value,
            debug_logging_until=user.debug_logging_until,
            created_at=user.created_at,
        )


class CreateUserRequest(BaseModel):
    login: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    role: Role


class InvitationResponse(BaseModel):
    id: str
    user_id: str
    url: str | None = None
    """The full single-use link. Present only in the response that issued it;
    only the token's hash is stored, so it cannot be produced again."""

    expires_at: datetime
    consumed_at: datetime | None = None

    @classmethod
    def of(cls, invitation: Invitation, *, url: str | None = None) -> InvitationResponse:
        return cls(
            id=invitation.id,
            user_id=invitation.user_id,
            url=url,
            expires_at=invitation.expires_at,
            consumed_at=invitation.consumed_at,
        )


class CreateUserResponse(BaseModel):
    user: UserResponse
    invitation: InvitationResponse


# --- authentication ------------------------------------------------------


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


class ConfirmTotpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)
