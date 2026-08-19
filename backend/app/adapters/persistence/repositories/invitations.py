"""Postgres invitations repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    InvitationRow,
    RecoveryCodeRow,
)
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode

from .shared import _Base


class PostgresInvitationRepository(_Base):
    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        row = await self._session.scalar(
            select(InvitationRow).where(InvitationRow.token_hash == token_hash)
        )
        return m.invitation_to_domain(row) if row else None

    async def save(self, invitation: Invitation) -> None:
        await self._session.merge(m.invitation_to_row(invitation))
        await self._session.flush()

    async def consume(self, invitation_id: str, at: datetime) -> bool:
        """Claim the invitation. Returns False if someone else already did.

        The `WHERE consumed_at IS NULL` makes the claim atomic, but the result
        has to be inspected for that to mean anything. Discarding it left both
        racers believing they had consumed the link, which is exactly the
        interception scenario the single-use rule exists for.
        """
        result = await self._session.execute(
            update(InvitationRow)
            .where(InvitationRow.id == invitation_id, InvitationRow.consumed_at.is_(None))
            .values(consumed_at=at)
        )
        # SQLAlchemy types async execute() as Result, which has no rowcount;
        # an UPDATE returns a CursorResult, which does. The cast is the stub gap,
        # not a runtime one.
        return cast("CursorResult[Any]", result).rowcount == 1

    async def invalidate_outstanding(self, user_id: str, purpose: InvitationPurpose) -> None:
        """Issuing a new link kills any earlier one.

        Without this, a reset link that was intercepted stays usable after the
        real user asks for another.
        """
        await self._session.execute(
            delete(InvitationRow).where(
                InvitationRow.user_id == user_id,
                InvitationRow.purpose == purpose.value,
                InvitationRow.consumed_at.is_(None),
            )
        )

    async def save_recovery_codes(self, codes: list[RecoveryCode]) -> None:
        self._session.add_all([m.recovery_code_to_row(c) for c in codes])
        await self._session.flush()

    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]:
        rows = (
            await self._session.scalars(
                select(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
            )
        ).all()
        return [m.recovery_code_to_domain(r) for r in rows]

    async def delete_recovery_codes(self, user_id: str) -> None:
        await self._session.execute(
            delete(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
        )

    async def delete_for_user(self, user_id: str) -> None:
        await self._session.execute(
            delete(RecoveryCodeRow).where(RecoveryCodeRow.user_id == user_id)
        )
        await self._session.execute(delete(InvitationRow).where(InvitationRow.user_id == user_id))

    async def consume_recovery_code(self, code_id: str, at: datetime) -> bool:
        """Same atomic claim, and the same reason to check it. A recovery code
        bypasses the second factor, so a code that can be redeemed twice is
        worse than an invitation that can."""
        result = await self._session.execute(
            update(RecoveryCodeRow)
            .where(RecoveryCodeRow.id == code_id, RecoveryCodeRow.used_at.is_(None))
            .values(used_at=at)
        )
        # SQLAlchemy types async execute() as Result, which has no rowcount;
        # an UPDATE returns a CursorResult, which does. The cast is the stub gap,
        # not a runtime one.
        return cast("CursorResult[Any]", result).rowcount == 1
