"""Which roles a caller may hand out.

`Scope.USER_WRITE` answers "may this caller create and edit accounts". It does
not answer "and with which role", and until 2026-08-04 nothing did — every
holder could assign every role. With two roles that was invisible, because the
only holder was `admin` and there was nothing above it to reach. Adding
`tenant_admin` made it an escalation path: create an account with `role:
admin`, receive its single-use onboarding link in the same response, and hold
`frozenset(Scope)` a minute later — including `TENANT_WRITE`, and including
every platform-global scope the role was specifically denied.

The rule is the smallest one that closes it and needs no table of its own:

    you may grant a role only if you already hold everything it confers.

So `admin` may grant anything, `tenant_admin` may grant `curator`, `auditor`,
`user` and its own role but not `operator` (which holds `NODE_WRITE`) or
`admin`, and `operator` may grant nothing at all because it lacks `USER_WRITE`
in the first place. Nobody can use account creation to acquire a scope they
did not already have, which is the property worth having — it stays true for
roles added later without anyone remembering this file exists.
"""

from __future__ import annotations

from app.domain.entities.actor import Actor, Role
from app.domain.exceptions import NotAuthorizedError
from app.domain.ports.security_ports import AuthorizationPort


def assert_may_grant(authz: AuthorizationPort, actor: Actor, role: Role) -> None:
    """Raise unless `actor` already holds every scope `role` confers."""
    conferred = authz.scopes_for(role.value)
    escalation = conferred - actor.scopes
    if escalation:
        # The detail names the scopes for the operator reading the audit log.
        # The response body says only "not authorized" — a caller probing which
        # role they can sneak past should learn nothing from the difference.
        raise NotAuthorizedError(
            detail=(
                f"{actor.display} may not grant {role.value}: it confers "
                f"{sorted(s.value for s in escalation)}, which they do not hold"
            )
        )
