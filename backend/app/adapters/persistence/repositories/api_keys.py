"""Postgres api keys repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    ApiKeyRow,
)
from app.domain.entities.api_key import ApiKey

from .shared import _TenantScoped


class PostgresApiKeyRepository(_TenantScoped):
    async def get_by_key_id(self, key_id: str) -> ApiKey | None:
        # Unscoped on the gateway's authentication path (the tenant is not known
        # until the key is found); scoped for management, so an admin cannot
        # reach another tenant's key by its handle.
        row = await self._session.scalar(
            self._scope(select(ApiKeyRow).where(ApiKeyRow.key_id == key_id), ApiKeyRow.tenant_id)
        )
        return m.api_key_to_domain(row) if row else None

    async def list_for_owner(self, owner_id: str) -> list[ApiKey]:
        rows = (
            await self._session.scalars(
                self._scope(
                    select(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id), ApiKeyRow.tenant_id
                )
            )
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def list_all(self) -> list[ApiKey]:
        rows = (
            await self._session.scalars(
                self._scope(
                    select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc()), ApiKeyRow.tenant_id
                )
            )
        ).all()
        return [m.api_key_to_domain(r) for r in rows]

    async def save(self, key: ApiKey) -> None:
        row = m.api_key_to_row(key)
        if self._tenant_id is not None:
            # Stamp rather than trust the entity, so a new key lands in this
            # repository's tenant regardless of what the use case set.
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def delete_for_owner(self, owner_id: str) -> None:
        await self._session.execute(
            self._scope(
                delete(ApiKeyRow).where(ApiKeyRow.owner_id == owner_id), ApiKeyRow.tenant_id
            )
        )

    async def revoke(self, key_id: str, at: datetime) -> None:
        # Only the first revocation writes a timestamp. Without the guard a
        # repeated call moves the recorded time forward, so "when was this
        # revoked" answers with the most recent attempt rather than the moment
        # it stopped working.
        await self._session.execute(
            self._scope(
                update(ApiKeyRow)
                .where(ApiKeyRow.key_id == key_id, ApiKeyRow.revoked_at.is_(None))
                .values(revoked_at=at),
                ApiKeyRow.tenant_id,
            )
        )

    async def update_settings(self, key_id: str, values: dict[str, object]) -> bool:
        """Targeted update of the editable columns, refused if revoked.

        A full-row `save` of a read-then-modified entity would write back
        `revoked_at` from the value it read, so an edit racing a concurrent
        `revoke` rerevived the key by overwriting the revocation with the NULL
        it had loaded. This touches only the named columns and requires
        `revoked_at IS NULL`, so it cannot revert a revocation and returns
        False if one landed first. The tenant scope means an admin cannot edit
        another tenant's key even by its handle.
        """
        result = await self._session.execute(
            self._scope(
                update(ApiKeyRow)
                .where(ApiKeyRow.key_id == key_id, ApiKeyRow.revoked_at.is_(None))
                .values(**values),
                ApiKeyRow.tenant_id,
            )
        )
        return (result.rowcount or 0) == 1  # type: ignore[attr-defined]
