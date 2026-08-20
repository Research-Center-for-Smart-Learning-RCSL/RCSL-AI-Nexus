"""Persistence identity boundary."""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network

from app.adapters.persistence.sqlalchemy_models import (
    ApiKeyRow,
    InvitationRow,
    RecoveryCodeRow,
    UserRow,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.user import User


def api_key_to_domain(row: ApiKeyRow) -> ApiKey:
    networks: list[IPv4Network | IPv6Network] = [
        ip_network(entry) for entry in row.allowed_cidrs or []
    ]
    return ApiKey(
        id=row.id,
        tenant_id=row.tenant_id,
        key_id=row.key_id,
        digest=row.digest,
        name=row.name,
        owner_id=row.owner_id,
        scopes=frozenset(row.scopes or []),
        allowed_cidrs=tuple(networks),
        rate_limit_rpm=row.rate_limit_rpm,
        quota_tokens_per_day=row.quota_tokens_per_day,
        default_capability=row.default_capability,
        expires_at=row.expires_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        debug_logging_until=row.debug_logging_until,
    )


def api_key_to_row(key: ApiKey) -> ApiKeyRow:
    row = ApiKeyRow(
        id=key.id,
        tenant_id=key.tenant_id,
        key_id=key.key_id,
        digest=key.digest,
        name=key.name,
        owner_id=key.owner_id,
        scopes=sorted(key.scopes),
        allowed_cidrs=[str(n) for n in key.allowed_cidrs],
        rate_limit_rpm=key.rate_limit_rpm,
        quota_tokens_per_day=key.quota_tokens_per_day,
        default_capability=key.default_capability,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        debug_logging_until=key.debug_logging_until,
    )
    if key.created_at is not None:
        # Left unset when the entity has never been persisted, so the column's
        # server default applies rather than a value computed in the process
        # that happens to be issuing the key.
        row.created_at = key.created_at
    return row


def user_to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        tenant_id=row.tenant_id,
        login=row.login,
        display_name=row.display_name,
        role=Role(row.role),
        tailscale_login=row.tailscale_login,
        password_hash=row.password_hash,
        totp_secret=row.totp_secret,
        totp_last_counter=row.totp_last_counter,
        created_at=row.created_at,
        debug_logging_until=row.debug_logging_until,
        disabled_at=row.disabled_at,
    )


def user_to_row_values(user: User) -> dict[str, object]:
    """Column values as a mapping, for statements that cannot take an ORM
    object: `insert_if_absent` builds an `ON CONFLICT` statement. Kept as the
    single definition of the column list so a new field cannot be added to one
    path and forgotten on the other."""
    values: dict[str, object] = {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "login": user.login,
        "display_name": user.display_name,
        "role": user.role.value,
        "tailscale_login": user.tailscale_login,
        "password_hash": user.password_hash,
        "totp_secret": user.totp_secret,
        "totp_last_counter": user.totp_last_counter,
        "debug_logging_until": user.debug_logging_until,
        "disabled_at": user.disabled_at,
    }
    if user.created_at is not None:
        # Omitted rather than passed as None when the entity has never been
        # persisted, so the column's server default applies. Passing None would
        # violate NOT NULL, and passing a value computed here would let a
        # client's clock decide when a row was created.
        values["created_at"] = user.created_at
    return values


def user_to_row(user: User) -> UserRow:
    return UserRow(**user_to_row_values(user))


def invitation_to_domain(row: InvitationRow) -> Invitation:
    return Invitation(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        purpose=InvitationPurpose(row.purpose),
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
    )


def invitation_to_row(invitation: Invitation) -> InvitationRow:
    return InvitationRow(
        id=invitation.id,
        user_id=invitation.user_id,
        token_hash=invitation.token_hash,
        purpose=invitation.purpose.value,
        expires_at=invitation.expires_at,
        consumed_at=invitation.consumed_at,
    )


def recovery_code_to_domain(row: RecoveryCodeRow) -> RecoveryCode:
    return RecoveryCode(
        id=row.id, user_id=row.user_id, code_hash=row.code_hash, used_at=row.used_at
    )


def recovery_code_to_row(code: RecoveryCode) -> RecoveryCodeRow:
    return RecoveryCodeRow(
        id=code.id, user_id=code.user_id, code_hash=code.code_hash, used_at=code.used_at
    )
