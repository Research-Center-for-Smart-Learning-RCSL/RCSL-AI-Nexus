"""Tenant management: the minimal platform operation that makes the isolation
boundary usable.

Tenants are platform-global, like nodes and models: an admin creates and lists
them, and they are not themselves tenant-scoped. Creating a tenant also mints its
first administrator's invitation, because a tenant with no administrator is a
boundary nobody can populate; that first admin then manages their own tenant
through the ordinary flows, whose repositories are scoped to it. See
docs/architecture/security.md section 7.3.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.application.use_cases.issue_invitation import IssuedInvitation, IssueInvitation
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.tenant import Tenant
from app.domain.exceptions import TenantStateConflictError
from app.domain.ports.repositories import TenantRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort


@dataclass(frozen=True, slots=True)
class TenantCreated:
    tenant: Tenant
    invitation: IssuedInvitation
    """The first administrator's onboarding link, returned once."""


class ManageTenants:
    def __init__(
        self,
        tenants: TenantRepositoryPort,
        invite: IssueInvitation,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._tenants = tenants
        self._invite = invite
        self._authz = authz
        self._audit = audit

    async def list_all(self, actor: Actor) -> list[Tenant]:
        self._authz.require(actor, Scope.TENANT_READ)
        return await self._tenants.list_all()

    async def create(
        self, actor: Actor, *, name: str, first_admin_login: str, first_admin_display_name: str
    ) -> TenantCreated:
        self._authz.require(actor, Scope.TENANT_WRITE)

        name = name.strip()
        if await self._tenants.get_by_name(name) is not None:
            # 409, consistent with how a taken model alias or node name is
            # reported rather than surfacing the unique-violation as a 500.
            raise TenantStateConflictError(detail=f"a tenant named {name!r} already exists")

        tenant = Tenant(id=str(uuid.uuid4()), name=name)
        await self._tenants.save(tenant)

        # The first admin is created in the new tenant, via an invitation issued
        # through an unscoped user repository so the explicit tenant lands rather
        # than the caller's. `create_account` also checks the login is free
        # platform-wide and audits `user.invited`.
        issued = await self._invite.create_account(
            actor,
            login=first_admin_login,
            display_name=first_admin_display_name,
            role=Role.ADMIN,
            tenant_id=tenant.id,
        )
        await self._audit.record(
            actor, AuditAction.TENANT_CREATED, target=tenant.id, detail={"name": name}
        )
        return TenantCreated(tenant=tenant, invitation=issued)
