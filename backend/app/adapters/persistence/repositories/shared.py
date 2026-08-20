"""Persistence shared boundary."""

from __future__ import annotations

from typing import Any, Self

from sqlalchemy.ext.asyncio import AsyncSession


class _Base:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session


class _TenantScoped:
    """A repository whose reads filter and whose writes stamp `tenant_id`.

    The filter lives here, in the adapter, and is taken from the tenant this
    repository was constructed with, never from a caller, so a use case cannot
    read or write another tenant's rows and cannot forget to say which tenant it
    means. The di builders construct these with the actor's tenant, so the wiring
    is the only place that decides. See docs/architecture/security.md section 7.3.

    `unscoped` builds one with no tenant, for the identity and bootstrap paths
    only: they resolve a principal (by session id, login, or key handle) before
    any tenant is known, and reading exactly the one row a unique handle names is
    not a cross-tenant enumeration. Every other construction passes a real tenant.
    """

    def __init__(self, session: AsyncSession, tenant_id: str | None) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @classmethod
    def unscoped(cls, session: AsyncSession) -> Self:
        return cls(session, None)

    def _scope(self, stmt: Any, column: Any) -> Any:
        """Add `column == tenant` unless this is an unscoped repository."""
        if self._tenant_id is None:
            return stmt
        return stmt.where(column == self._tenant_id)
