"""Audit subjects for flows that have no authenticated actor yet.

Signing in, accepting an invitation and consuming a reset link all produce
events section 12 requires, and none of them has an `Actor`: that is the thing
they are in the middle of establishing. The audit row still needs a subject, so
these build one.

**The result is a label, not a credential.** `scopes` is always empty, so an
actor from here cannot satisfy any `AuthorizationPort.require`. Nothing should
pass one of these anywhere except to `AuditPort.record`; if it ever reaches a
use case, the empty scope set is what makes that fail rather than succeed
quietly.
"""

from __future__ import annotations

import hashlib

from app.domain.entities.actor import Actor, Role
from app.domain.entities.user import User

UNKNOWN_ACTOR_ID = "unknown"
"""Not a user id, and deliberately not one that could collide with a uuid."""


def subject_for(user: User) -> Actor:
    """The account holder, acting on their own account.

    Recording these as the platform or as the administrator who issued the
    invitation would both misattribute them. `source` is `local` because that
    is the entrance these flows belong to; the tailnet entrance has no
    password step and no invitation to accept.

    `tenant_id` is carried across. Without it the row lands in the default
    tenant, and the logs screen is tenant-scoped, so a tenant's own sign-ins
    would be missing from the only view they can read.
    """
    return Actor(
        id=user.id,
        display=user.login,
        role=Role(user.role),
        source="local",
        scopes=frozenset(),
        tenant_id=user.tenant_id,
    )


def unknown_subject(login: str) -> Actor:
    """A failed attempt against a login that matches no account.

    There is no user to name, and an investigator asking "what was tried
    against this instance" needs the string that was presented — so it is
    recorded, but only when it is shaped like a login.

    **The redaction is not about the attacker.** Logins here are `EmailStr` at
    creation, so a real one always has an address's shape. The string that
    reaches this function without one is most often a person typing their
    password into the login field, and storing it verbatim would put a live
    credential into a table kept for a year and readable by anyone holding
    `logs:read` — the one thing section 12 says the log must never carry.
    `LoginThrottle` already digests the login for the same reason, so its
    counters cannot accumulate a list of valid addresses.

    The digest keeps distinct attempts distinguishable, which is what the value
    was wanted for: repeats of one string still group, and it can be confirmed
    against a suspected value by hashing that value.

    `id` is a fixed sentinel rather than a random value, so the rows group. The
    tenant is the default one because no tenant can be resolved: an unknown
    login belongs to none of them.
    """
    return Actor(
        id=UNKNOWN_ACTOR_ID,
        display=login if _is_login_shaped(login) else _redacted(login),
        role=Role.USER,
        source="local",
        scopes=frozenset(),
    )


def _is_login_shaped(presented: str) -> bool:
    """Deliberately loose. This decides whether to keep a string, not whether
    to accept one, so anything address-like is worth recording as typed; the
    narrow case being caught is a value with no `@` in it at all."""
    name, separator, domain = presented.partition("@")
    return bool(separator and name and "." in domain)


def _redacted(presented: str) -> str:
    return f"redacted:{hashlib.sha256(presented.encode()).hexdigest()[:32]}"
