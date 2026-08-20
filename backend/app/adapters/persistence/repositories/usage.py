"""Persistence usage boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.adapters.persistence import mappers as m
from app.adapters.persistence.sqlalchemy_models import (
    UsageRecordRow,
)
from app.domain.entities.usage import BucketUnit, UsageBucket, UsageRecord

from .shared import _TenantScoped


class PostgresUsageRepository(_TenantScoped):
    async def record(self, usage: UsageRecord) -> None:
        row = m.usage_to_row(usage)
        if self._tenant_id is not None:
            # Stamp from the gateway's scoped repository, so usage lands under
            # the tenant of the key that produced it regardless of the entity.
            row.tenant_id = self._tenant_id
        self._session.add(row)

    async def tokens_used_today(self, api_key_id: str) -> int:
        # Both halves. `quota_tokens_per_day` charged for generated tokens
        # alone until 2026-08-04, so a caller could fill the context window on
        # every request and spend none of its quota doing it — on this
        # hardware, prompt evaluation is most of the wait.
        since = datetime.now(UTC) - timedelta(days=1)
        total = await self._session.scalar(
            self._scope(
                select(
                    func.coalesce(func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens), 0)
                ).where(
                    UsageRecordRow.api_key_id == api_key_id,
                    UsageRecordRow.at >= since,
                ),
                UsageRecordRow.tenant_id,
            )
        )
        return int(total or 0)

    async def quota_recovers_at(
        self, api_key_id: str, *, tokens_to_release: int
    ) -> datetime | None:
        """When enough spend will have aged out for the key to be admitted again.

        The window `tokens_used_today` reads is rolling, not a calendar day, so
        an exhausted quota does not clear at midnight and it does not clear all
        at once: it clears one past request at a time, as each falls out of the
        trailing 24 hours. This walks the same rows in order and returns the
        moment the oldest `tokens_to_release` tokens have gone.

        Returns None when the window holds less than that, which can only mean
        the caller's arithmetic disagrees with the table — the quota check that
        prompts this call reads both figures from the same rows.
        """
        since = datetime.now(UTC) - timedelta(days=1)
        running = (
            func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens)
            .over(order_by=UsageRecordRow.at)
            .label("released")
        )
        window = self._scope(
            select(UsageRecordRow.at.label("at"), running).where(
                UsageRecordRow.api_key_id == api_key_id,
                UsageRecordRow.at >= since,
            ),
            UsageRecordRow.tenant_id,
        ).subquery()

        # The row that tips the running total past what has to be released; it
        # is still inside the window until 24 hours after it was written.
        oldest = await self._session.scalar(
            select(func.min(window.c.at)).where(window.c.released >= tokens_to_release)
        )
        return oldest + timedelta(days=1) if oldest is not None else None

    async def last_used_by_key(self) -> dict[str, datetime]:
        """One aggregate for every key, not one query per key.

        `api_keys` has no `last_used_at` column on purpose: writing it would
        mean the gateway updating that table on every request, and the account
        split in security.md section 6 exists precisely so a compromised
        gateway cannot write there. The same fact is already in this table,
        under the index `ix_usage_key_at`. Scoped, so a tenant's dashboard sees
        only its own keys' activity.
        """
        rows = await self._session.execute(
            self._scope(
                select(UsageRecordRow.api_key_id, func.max(UsageRecordRow.at))
                .where(UsageRecordRow.api_key_id.is_not(None))
                .group_by(UsageRecordRow.api_key_id),
                UsageRecordRow.tenant_id,
            )
        )
        return {key_id: at for key_id, at in rows if key_id is not None}

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        row = (
            await self._session.execute(
                self._scope(
                    select(
                        func.count(),
                        # Both halves, matching the quota: a dashboard that
                        # counted only output would disagree with the number
                        # the caller is actually charged.
                        func.coalesce(
                            func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens), 0
                        ),
                    ).where(UsageRecordRow.at >= since),
                    UsageRecordRow.tenant_id,
                )
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    async def bucketed_usage(
        self,
        since: datetime,
        until: datetime,
        unit: BucketUnit,
        *,
        actor_id: str | None = None,
    ) -> list[UsageBucket]:
        # `unit` reaches date_trunc as a bind parameter, not interpolated text,
        # and the use case restricts it to the BucketUnit literals regardless.
        bucket = func.date_trunc(unit, UsageRecordRow.at)
        where = [UsageRecordRow.at >= since, UsageRecordRow.at < until]
        # Narrowed *inside* `_scope`, never instead of it: one account's usage is
        # still read within its tenant's boundary, so an actor id that belonged
        # to another tenant would select nothing rather than crossing it.
        if actor_id is not None:
            where.append(UsageRecordRow.actor_id == actor_id)
        rows = await self._session.execute(
            self._scope(
                select(
                    bucket.label("bucket"),
                    UsageRecordRow.capability,
                    func.count(),
                    # Both halves, as above, so the chart and the quota agree.
                    func.coalesce(
                        func.sum(UsageRecordRow.tokens + UsageRecordRow.prompt_tokens), 0
                    ),
                )
                .where(*where)
                .group_by(bucket, UsageRecordRow.capability)
                .order_by(bucket),
                UsageRecordRow.tenant_id,
            )
        )
        return [
            UsageBucket(
                bucket_start=start,
                capability=capability,
                requests=int(requests or 0),
                tokens=int(tokens or 0),
            )
            for start, capability, requests, tokens in rows
        ]
