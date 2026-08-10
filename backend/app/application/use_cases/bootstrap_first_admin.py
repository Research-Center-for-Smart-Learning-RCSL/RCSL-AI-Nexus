"""First-administrator bootstrap.

A fresh deployment has an empty `users` table, so every authenticated identity
resolves to an unknown role and nobody can reach the management UI, including
the person who deployed it.

Three conditions, all required, all narrow on purpose. See
docs/architecture/security.md section 5.5.

1. `BOOTSTRAP_ADMIN_LOGIN` names one Tailscale login, and only that login.
2. It applies only while the table is empty, so the setting is inert forever
   after the first success and does not need removing.
3. It is reachable only from the tailnet entrance. Were it available publicly,
   whoever found a freshly deployed instance first would become its
   administrator, and that is a race an operator can lose to a scanner.

The account is created **without local credentials**, because the tailnet
entrance does not use them. If that person later needs the public entrance,
they issue themselves an invitation through the ordinary flow.
"""

from __future__ import annotations

import logging
import uuid

from app.domain.entities.actor import Actor, Role
from app.domain.entities.audit import AuditAction
from app.domain.entities.user import User
from app.domain.ports.repositories import UserRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

logger = logging.getLogger(__name__)


class BootstrapFirstAdmin:
    def __init__(
        self,
        users: UserRepositoryPort,
        audit: AuditPort,
        authz: AuthorizationPort,
        *,
        bootstrap_login: str,
    ) -> None:
        self._users = users
        self._audit = audit
        self._authz = authz
        self._bootstrap_login = bootstrap_login.strip().lower()

    async def claim(self, tailscale_login: str, display_name: str) -> User | None:
        """Return the created administrator, or None if bootstrap does not apply.

        None is the ordinary answer on every request after the first, so the
        caller treats it as "no identity from this path" rather than an error.
        """
        if not self._bootstrap_login:
            return None

        if tailscale_login.strip().lower() != self._bootstrap_login:
            return None

        if await self._users.count() > 0:
            return None

        candidate = User(
            id=str(uuid.uuid4()),
            login=tailscale_login,
            display_name=display_name or tailscale_login,
            role=Role.ADMIN,
            tailscale_login=tailscale_login,
        )
        # Atomic: several requests from one page load reach this together.
        created = await self._users.insert_if_absent(candidate)

        actor = Actor(
            id=created.id,
            display=created.login,
            role=created.role,
            source="tailnet",
            scopes=self._authz.scopes_for(created.role.value),
        )
        await self._audit.record(
            actor,
            AuditAction.BOOTSTRAP_FIRST_ADMIN,
            target=created.id,
            detail={"login": created.login},
        )
        logger.warning(
            "bootstrap_first_admin login=%s id=%s: BOOTSTRAP_ADMIN_LOGIN is now inert",
            created.login,
            created.id,
        )
        return created
