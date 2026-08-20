"""Admin users tenants schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.entities.invitation import Invitation
from app.domain.entities.tenant import Tenant
from app.domain.entities.user import User
from app.domain.services.debug_window import MAX_DEBUG_WINDOW_MINUTES

from .shared import HumanRole


class RoleResponse(BaseModel):
    """One row of the role catalogue.

    Carries the scope list rather than prose. The wording that explains a role
    to a person is copy and lives in the UI; the list of what it actually
    grants is derived from the authorization table, so the two cannot disagree
    about the part that matters."""

    role: str
    scopes: list[str]


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
    role: HumanRole


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


class TenantResponse(BaseModel):
    id: str
    name: str
    created_at: datetime | None

    @classmethod
    def of(cls, tenant: Tenant) -> TenantResponse:
        return cls(id=tenant.id, name=tenant.name, created_at=tenant.created_at)


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    first_admin_login: EmailStr
    """A tenant with no administrator cannot be populated, so creating one mints
    its first admin's invitation. The login is globally unique, like every other."""

    first_admin_display_name: str = Field(min_length=1, max_length=120)


class CreateTenantResponse(BaseModel):
    tenant: TenantResponse
    invitation: InvitationResponse
    """The first administrator's onboarding link, present here and nowhere else."""


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: HumanRole | None = None
    disabled: bool | None = None


class SetDebugWindowRequest(BaseModel):
    """Shared by the API-key and user windows, which are one control on two
    credentials (`domain/services/debug_window.py`)."""

    minutes: int = Field(ge=0, le=MAX_DEBUG_WINDOW_MINUTES)
    """0 closes the window. The ceiling is imported rather than restated, so
    the form's limit and the rule it enforces cannot drift apart."""
