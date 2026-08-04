"""Setting a retention window, previewing a purge, and purging.

The three properties worth pinning are the ones that would be expensive to
discover in production: only an administrator can reach any of it, a preview
deletes nothing, and the floor is refused rather than quietly clamped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_retention import ManageRetention
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.retention import (
    DEFAULT_RETENTION_DAYS,
    MINIMUM_RETENTION_DAYS,
    RetentionDataset,
    RetentionPolicy,
)
from app.domain.exceptions import NotAuthorizedError, RetentionWindowTooShortError
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
) -> tuple[ManageRetention, FakePurge, FakePurge, FakeAudit]:
    audit_rows = audit or FakePurge([])
    usage_rows = usage or FakePurge([])
    trail = FakeAudit()
    use_case = ManageRetention(
        policies=policies or FakePolicies(),
        purges={
            RetentionDataset.AUDIT_LOG: audit_rows,
            RetentionDataset.USAGE_RECORDS: usage_rows,
        },
        authz=_AUTHZ,
        audit=trail,
        clock=FakeClock(),
    )
    return use_case, audit_rows, usage_rows, trail


# --- who may reach it ----------------------------------------------------


@pytest.mark.parametrize("scope", [Scope.LOGS_READ, Scope.USAGE_READ_ALL, Scope.USER_WRITE])
async def test_every_operation_refuses_a_scope_that_is_not_retention_write(scope: Scope) -> None:
    """Including the read. The number is of no interest to anyone who cannot
    change it, which is why one scope covers all three."""
    use_case, *_ = _build()
    actor = _actor(scope)

    with pytest.raises(NotAuthorizedError):
        await use_case.list_policies(actor)
    with pytest.raises(NotAuthorizedError):
        await use_case.preview(actor, RetentionDataset.AUDIT_LOG)
    with pytest.raises(NotAuthorizedError):
        await use_case.set_policy(actor, RetentionDataset.AUDIT_LOG, 90)
    with pytest.raises(NotAuthorizedError):
        await use_case.purge(actor, RetentionDataset.AUDIT_LOG)


# --- the policy ----------------------------------------------------------


async def test_a_dataset_nobody_configured_still_reports_the_default() -> None:
    # The alternative — listing only stored rows — shows an empty screen on a
    # fresh deployment and implies nothing ever expires.
    use_case, *_ = _build()

    policies = await use_case.list_policies(_actor(Scope.RETENTION_WRITE))

    assert {p.dataset for p in policies} == set(RetentionDataset)
    assert {p.days for p in policies} == {DEFAULT_RETENTION_DAYS}
    assert all(p.updated_by is None for p in policies)


async def test_setting_a_window_records_who_set_it_and_audits_the_change() -> None:
    use_case, _, _, trail = _build()

    policy = await use_case.set_policy(
        _actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG, 90
    )

    assert policy.days == 90
    assert policy.updated_by == "admin@example.test"
    assert policy.updated_at == NOW
    assert ("retention.policy_set", "audit_log", "success") in trail.entries


async def test_a_window_under_the_floor_is_refused_not_clamped() -> None:
    """Clamping would store a number the administrator did not type and report
    success, which puts the gap between choice and effect where nobody looks."""
    use_case, *_ = _build()
    actor = _actor(Scope.RETENTION_WRITE)

    with pytest.raises(RetentionWindowTooShortError):
        await use_case.set_policy(actor, RetentionDataset.AUDIT_LOG, MINIMUM_RETENTION_DAYS - 1)

    stored = await use_case.list_policies(actor)
    assert {p.days for p in stored} == {DEFAULT_RETENTION_DAYS}


# --- preview and purge ---------------------------------------------------


def _rows_spanning_a_year() -> FakePurge:
    return FakePurge([NOW - timedelta(days=n) for n in (1, 100, 300, 400, 500)])


async def test_a_preview_counts_without_deleting() -> None:
    """The assertion that matters is the second one: a dry run sharing a code
    path with the real thing is one edit away from deleting during a preview."""
    audit_rows = _rows_spanning_a_year()
    use_case, _, _, _ = _build(audit=audit_rows)

    preview = await use_case.preview(_actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG)

    assert preview.days == DEFAULT_RETENTION_DAYS
    assert preview.affected == 2  # 400 and 500 days old
    assert audit_rows.deleted_at_cutoffs == []
    assert len(audit_rows.ats) == 5


async def test_a_preview_can_answer_for_a_window_that_is_not_stored_yet() -> None:
    # What lets the form say "saving this removes 4 rows" before it is saved.
    audit_rows = _rows_spanning_a_year()
    use_case, _, _, _ = _build(audit=audit_rows)

    preview = await use_case.preview(
        _actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG, days=90
    )

    assert preview.days == 90
    assert preview.affected == 4
    assert audit_rows.deleted_at_cutoffs == []


async def test_purging_removes_only_what_is_past_the_window_and_audits_the_count() -> None:
    audit_rows = _rows_spanning_a_year()
    use_case, _, usage_rows, trail = _build(audit=audit_rows, usage=_rows_spanning_a_year())

    outcome = await use_case.purge(_actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG)

    assert outcome.deleted == 2
    assert outcome.cutoff == NOW - timedelta(days=DEFAULT_RETENTION_DAYS)
    assert len(audit_rows.ats) == 3
    # Aimed at one dataset, and the other is untouched — this is the "clear this
    # specific thing" case the administrator asked for.
    assert len(usage_rows.ats) == 5
    assert ("retention.purged", "audit_log", "success") in trail.entries
    recorded = [row for row in trail.rows if row[1] == "retention.purged"][0]
    assert recorded[4]["deleted"] == "2"


async def test_a_purge_may_be_narrower_than_the_policy_without_changing_it() -> None:
    policies = FakePolicies()
    use_case, audit_rows, _, _ = _build(policies=policies, audit=_rows_spanning_a_year())
    actor = _actor(Scope.RETENTION_WRITE)

    outcome = await use_case.purge(actor, RetentionDataset.AUDIT_LOG, days=90)

    assert outcome.deleted == 4
    assert policies.stored == {}, "a one-off purge is not a policy change"


async def test_a_purge_narrower_than_the_floor_is_refused() -> None:
    use_case, audit_rows, _, _ = _build(audit=_rows_spanning_a_year())

    with pytest.raises(RetentionWindowTooShortError):
        await use_case.purge(_actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG, days=1)

    assert audit_rows.deleted_at_cutoffs == []


# --- the scheduled sweep -------------------------------------------------


async def test_the_sweep_applies_every_stored_policy_and_needs_no_actor() -> None:
    """It runs on a timer inside the admin application, so there is nobody to
    authorise. That is why it is a separate method rather than `purge` with a
    null actor threaded past the scope check."""
    policies = FakePolicies([RetentionPolicy(dataset=RetentionDataset.USAGE_RECORDS, days=90)])
    use_case, audit_rows, usage_rows, _ = _build(
        policies=policies, audit=_rows_spanning_a_year(), usage=_rows_spanning_a_year()
    )

    outcomes = {o.dataset: o.deleted for o in await use_case.purge_due()}

    # audit_log is on the default 360; usage_records was set to 90.
    assert outcomes == {RetentionDataset.AUDIT_LOG: 2, RetentionDataset.USAGE_RECORDS: 4}
    assert len(audit_rows.ats) == 3
    assert len(usage_rows.ats) == 1


async def test_the_sweep_reports_zero_rather_than_skipping_an_empty_dataset() -> None:
    # So one log line can describe a whole sweep.
    use_case, *_ = _build()

    outcomes = await use_case.purge_due()

    assert [o.deleted for o in outcomes] == [0, 0]
    assert {o.dataset for o in outcomes} == set(RetentionDataset)
