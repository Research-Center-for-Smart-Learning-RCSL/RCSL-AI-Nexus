"""Persistence retention templates boundary."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    AuditLogRow,
    PromptLogRow,
    PromptTemplateRow,
    RefusalRow,
    RetentionPolicyRow,
    UsageRecordRow,
)
from app.domain.entities.prompt_template import PromptTemplate
from app.domain.entities.retention import RetentionDataset, RetentionPolicy

from .shared import _TenantScoped

logger = logging.getLogger(__name__)


class PostgresRecordPurge:
    """Counting and deleting by age, for one table.

    Constructed with the row class rather than subclassed per dataset: the
    tables this serves have nothing in common but an indexed `at` column, and a
    class each would be three copies of the same four lines drifting apart.

    The union in the signature is deliberately spelled out rather than widened
    to `type[Base]`. Every member of it is a table an administrator has decided
    may be deleted from, which is the same closed-set reasoning `RetentionDataset`
    carries: this class ends in a `DELETE`, and what it may be aimed at should
    be a list somebody has to edit rather than anything with an `at` column.

    Not `_TenantScoped`, and that is the point rather than an omission — see
    `RecordPurgePort`. Retention is platform-wide, held by an administrator who
    is not confined to a tenant, and a purge that quietly spared other tenants
    would report a count that did not describe what it did.
    """

    def __init__(
        self,
        session: AsyncSession,
        row: type[UsageRecordRow] | type[AuditLogRow] | type[PromptLogRow] | type[RefusalRow],
    ) -> None:
        self._session = session
        self._row = row

    async def count_older_than(self, cutoff: datetime) -> int:
        total = await self._session.scalar(
            select(func.count()).select_from(self._row).where(self._row.at < cutoff)
        )
        return int(total or 0)

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = cast(
            CursorResult[Any],
            await self._session.execute(delete(self._row).where(self._row.at < cutoff)),
        )
        return int(result.rowcount or 0)


class PostgresRetentionPolicyRepository:
    """The configured windows. No tenant scope, for the reason above."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_policies(self) -> list[RetentionPolicy]:
        rows = await self._session.scalars(select(RetentionPolicyRow))
        return [m.retention_row_to_domain(row) for row in rows]

    async def get_policy(self, dataset: RetentionDataset) -> RetentionPolicy | None:
        row = await self._session.get(RetentionPolicyRow, dataset.value)
        return m.retention_row_to_domain(row) if row else None

    async def set_policy(self, policy: RetentionPolicy) -> None:
        # Upsert rather than read-then-write: two administrators saving the same
        # screen at once should leave the later value, not an integrity error
        # on a primary key neither of them chose.
        stmt = pg_insert(RetentionPolicyRow).values(
            dataset=policy.dataset.value,
            days=policy.days,
            updated_at=policy.updated_at,
            updated_by=policy.updated_by,
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[RetentionPolicyRow.dataset],
                set_={
                    "days": stmt.excluded.days,
                    "updated_at": stmt.excluded.updated_at,
                    "updated_by": stmt.excluded.updated_by,
                },
            )
        )


class PostgresPromptTemplateRepository(_TenantScoped):
    """Prompt templates, filtered and stamped like every other tenant's content.

    `get_by_name` is the one a chat request goes through, and the scope on it is
    the whole of what keeps a caller-supplied name honest: the string arrives in
    the request body, so unscoped it would be a way to read another tenant's
    template by guessing what they called it.
    """

    async def get(self, template_id: str) -> PromptTemplate | None:
        stmt = self._scope(
            select(PromptTemplateRow).where(PromptTemplateRow.id == template_id),
            PromptTemplateRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        return m.prompt_template_to_domain(row) if row else None

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        stmt = self._scope(
            select(PromptTemplateRow).where(PromptTemplateRow.name == name),
            PromptTemplateRow.tenant_id,
        )
        row = await self._session.scalar(stmt)
        return m.prompt_template_to_domain(row) if row else None

    async def list_all(self) -> list[PromptTemplate]:
        stmt = self._scope(
            select(PromptTemplateRow).order_by(PromptTemplateRow.name),
            PromptTemplateRow.tenant_id,
        )
        rows = (await self._session.scalars(stmt)).all()
        return [m.prompt_template_to_domain(r) for r in rows]

    async def save(self, template: PromptTemplate) -> None:
        row = m.prompt_template_to_row(template)
        if self._tenant_id is not None:
            # Stamped rather than trusted, as every scoped write here is.
            row.tenant_id = self._tenant_id
        await self._session.merge(row)
        await self._session.flush()

    async def delete(self, template_id: str) -> None:
        stmt = self._scope(
            delete(PromptTemplateRow).where(PromptTemplateRow.id == template_id),
            PromptTemplateRow.tenant_id,
        )
        await self._session.execute(stmt)
