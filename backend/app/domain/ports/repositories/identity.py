"""Persistence identity boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.entities.api_key import ApiKey
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.user import User


class ApiKeyRepositoryPort(Protocol):
    async def get_by_key_id(self, key_id: str) -> ApiKey | None: ...
    async def list_for_owner(self, owner_id: str) -> list[ApiKey]: ...
    async def list_all(self) -> list[ApiKey]: ...
    async def save(self, key: ApiKey) -> None: ...
    async def revoke(self, key_id: str, at: datetime) -> None: ...

    async def update_settings(self, key_id: str, values: dict[str, object]) -> bool:
        """Update only the editable columns, refused if the key is revoked.

        A full-row save of a read-then-modified key writes `revoked_at` back
        from what it read, reviving a key a concurrent `revoke` had just
        killed. This touches named columns only, requires `revoked_at IS NULL`,
        and returns False if a revocation won the race.
        """
        ...

    async def delete_for_owner(self, owner_id: str) -> None:
        """Needed to delete a user: `api_keys.owner_id` is a foreign key, so
        the rows have to go with them. The use case decides whether deleting a
        user with live keys is allowed at all."""
        ...


class UserRepositoryPort(Protocol):
    async def get(self, user_id: str) -> User | None: ...
    async def get_by_login(self, login: str) -> User | None: ...
    async def get_by_tailscale_login(self, login: str) -> User | None: ...
    async def list_all(self) -> list[User]: ...

    async def display_names(self) -> dict[str, str]:
        """User id to display name, and nothing else.

        The API-key listing needs to label each key's owner. Loading the full
        `User` entity for that pulls `password_hash` and `totp_secret` into a
        handler a `user`-role caller can reach, one edit away from leaking
        them; this reads only the two columns a label needs.
        """
        ...

    async def count(self) -> int:
        """Used by the bootstrap check: the first-admin setting is inert once
        any user exists."""
        ...

    async def save(self, user: User) -> None:
        """Full-row upsert; the entity must be complete or omitted columns are
        blanked. Prefer the targeted updates below where one exists."""
        ...

    async def insert_if_absent(self, user: User) -> User:
        """Insert, or return whichever row already holds this login.

        Exists for the first-admin bootstrap, where the guard is "no users
        yet" and a browser's first page load fires several requests at once.
        All of them see an empty table, all of them try to create the same
        account, and without an atomic claim the losers raise a constraint
        violation at commit. Returning the winner's row makes them agree
        instead.
        """
        ...

    async def advance_totp_counter(self, user_id: str, counter: int) -> bool:
        """Claim a TOTP counter, False if it is not newer than the stored one."""
        ...

    async def set_disabled(self, user_id: str, at: datetime | None) -> None: ...

    async def update_profile(self, user_id: str, *, display_name: str, role: str) -> None:
        """Update only display name and role, so a full-row save cannot revert
        a concurrent disable or TOTP-counter advance."""
        ...

    async def set_debug_logging_until(self, user_id: str, until: datetime | None) -> bool:
        """Open or close the account's debug window, False if it is disabled.

        Conditional on `disabled_at IS NULL` in the UPDATE rather than checked
        beforehand, for the reason `advance_totp_counter` gives: a read, a
        Python comparison and a write lets a concurrent disable land in
        between, and the window would then be open on an account somebody has
        just shut off.
        """
        ...

    async def delete(self, user_id: str) -> None: ...

    async def count_admins(self) -> int:
        """Guards the last administrator. Removing the only one leaves an
        instance nobody can manage, and the bootstrap setting does not come
        back: it is inert once any user row exists."""
        ...


class InvitationRepositoryPort(Protocol):
    async def get_by_token_hash(self, token_hash: str) -> Invitation | None: ...
    async def save(self, invitation: Invitation) -> None: ...

    async def consume(self, invitation_id: str, at: datetime) -> bool:
        """False when another request claimed it first. Callers must check:
        the atomic guard is meaningless if its result is discarded."""
        ...

    async def invalidate_outstanding(self, user_id: str, purpose: InvitationPurpose) -> None: ...

    async def save_recovery_codes(self, codes: list[RecoveryCode]) -> None: ...
    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]: ...

    async def delete_recovery_codes(self, user_id: str) -> None:
        """Re-enrolling the second factor issues a fresh set.

        The old codes must go in the same transaction, or a set printed
        against a secret the user no longer holds stays redeemable, which is a
        standing bypass of the factor they just replaced.
        """
        ...

    async def delete_for_user(self, user_id: str) -> None:
        """Every invitation and recovery code belonging to a user.

        Both tables carry a foreign key to `users`, so deleting an account
        without this leaves the delete itself impossible. It also means an
        outstanding invitation cannot outlive the account it was issued for.
        """
        ...

    async def consume_recovery_code(self, code_id: str, at: datetime) -> bool: ...
