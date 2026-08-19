"""Setting a retention window, previewing a purge, and purging.

The three properties worth pinning are the ones that would be expensive to
discover in production: only an administrator can reach any of it, a preview
deletes nothing, and the floor is refused rather than quietly clamped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_retention import ManageRetention
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.retention import (
    RetentionDataset,
    RetentionPolicy,
)
from tests.unit.fakes import FakeAudit

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

_AUTHZ = RoleAuthorization()


def _actor(*scopes: Scope) -> Actor:
    return Actor(
        id="a1",
        display="admin@example.test",
        role=Role.ADMIN,
        source="local",
        scopes=frozenset(scopes),
        tenant_id="t1",
    )


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakePolicies:
    def __init__(self, stored: list[RetentionPolicy] | None = None) -> None:
        self.stored = {p.dataset: p for p in (stored or [])}

    async def list_policies(self) -> list[RetentionPolicy]:
        return list(self.stored.values())

    async def get_policy(self, dataset: RetentionDataset) -> RetentionPolicy | None:
        return self.stored.get(dataset)

    async def set_policy(self, policy: RetentionPolicy) -> None:
        self.stored[policy.dataset] = policy


class FakePurge:
    """Rows as a list of timestamps. `deleted` records every cutoff it was
    asked to delete at, so a preview that deleted would be visible as an entry
    nobody expected rather than as a count that happened to match."""

    def __init__(self, ats: list[datetime]) -> None:
        self.ats = list(ats)
        self.deleted_at_cutoffs: list[datetime] = []

    async def count_older_than(self, cutoff: datetime) -> int:
        return len([a for a in self.ats if a < cutoff])

    async def delete_older_than(self, cutoff: datetime) -> int:
        self.deleted_at_cutoffs.append(cutoff)
        keep = [a for a in self.ats if a >= cutoff]
        removed = len(self.ats) - len(keep)
        self.ats = keep
        return removed


def _build(
    policies: FakePolicies | None = None,
    audit: FakePurge | None = None,
    usage: FakePurge | None = None,
    prompt: FakePurge | None = None,
) -> tuple[ManageRetention, FakePurge, FakePurge, FakePurge, FakeAudit]:
    audit_rows = audit or FakePurge([])
    usage_rows = usage or FakePurge([])
    prompt_rows = prompt or FakePurge([])
    trail = FakeAudit()
    use_case = ManageRetention(
        policies=policies or FakePolicies(),
        # Every dataset, because the use case now refuses to construct without
        # one apiece — see `test_a_missing_purge_is_refused_at_construction`.
        purges={
            RetentionDataset.AUDIT_LOG: audit_rows,
            RetentionDataset.USAGE_RECORDS: usage_rows,
            RetentionDataset.PROMPT_LOGS: prompt_rows,
            RetentionDataset.REFUSALS: FakePurge([]),
        },
        authz=_AUTHZ,
        audit=trail,
        clock=FakeClock(),
    )
    return use_case, audit_rows, usage_rows, prompt_rows, trail


def _rows_spanning_a_year() -> FakePurge:
    return FakePurge([NOW - timedelta(days=n) for n in (1, 100, 300, 400, 500)])
