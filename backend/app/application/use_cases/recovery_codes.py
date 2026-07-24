"""Issuing a fresh set of recovery codes.

Shared by invitation acceptance and by re-enrolment from account settings,
because the rule that makes it correct is the same in both and is easy to get
half right: **the previous set is deleted in the same transaction.** A set
printed against a secret the user no longer holds stays redeemable otherwise,
and since a recovery code bypasses the second factor outright, that is a
standing bypass of the factor that was just replaced.

Ten single-use codes, hashed at rest, displayed exactly once. Without them a
lost phone means an administrator resets the account by hand, and in the worst
case nobody can reach the platform at all. See
docs/architecture/security.md section 5.3.
"""

from __future__ import annotations

import uuid

from app.domain.entities.invitation import RecoveryCode
from app.domain.ports.repositories import InvitationRepositoryPort
from app.domain.services.token_service import TokenService


async def reissue_recovery_codes(
    invitations: InvitationRepositoryPort,
    tokens: TokenService,
    user_id: str,
) -> list[str]:
    """Returns the plaintext codes. This is their only appearance."""
    await invitations.delete_recovery_codes(user_id)

    issued = tokens.issue_recovery_codes()
    await invitations.save_recovery_codes(
        [
            RecoveryCode(id=str(uuid.uuid4()), user_id=user_id, code_hash=code.hashed)
            for code in issued
        ]
    )
    return [code.plaintext for code in issued]
