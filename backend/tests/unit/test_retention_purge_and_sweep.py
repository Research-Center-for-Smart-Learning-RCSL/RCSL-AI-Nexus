from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.use_cases.manage_retention import ManageRetention
from app.domain.entities.actor import Scope
from app.domain.entities.retention import (
    DEFAULT_RETENTION_DAYS,
    RetentionDataset,
    RetentionPolicy,
    bounds_for,
)
from app.domain.exceptions import (
    RetentionWindowTooShortError,
)
from tests.unit.fakes import FakeAudit
from tests.unit.manage_retention_fixtures import (
    _AUTHZ,
    NOW,
    FakeClock,
    FakePolicies,
    FakePurge,
    _actor,
    _build,
    _rows_spanning_a_year,
)

pytest_plugins = ("tests.unit.manage_retention_fixtures",)


async def test_a_preview_counts_without_deleting() -> None:
    """The assertion that matters is the second one: a dry run sharing a code
    path with the real thing is one edit away from deleting during a preview."""
    audit_rows = _rows_spanning_a_year()
    use_case, *_ = _build(audit=audit_rows)

    preview = await use_case.preview(_actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG)

    assert preview.days == DEFAULT_RETENTION_DAYS
    assert preview.affected == 2  # 400 and 500 days old
    assert audit_rows.deleted_at_cutoffs == []
    assert len(audit_rows.ats) == 5


async def test_a_preview_can_answer_for_a_window_that_is_not_stored_yet() -> None:
    # What lets the form say "saving this removes 4 rows" before it is saved.
    audit_rows = _rows_spanning_a_year()
    use_case, *_ = _build(audit=audit_rows)

    preview = await use_case.preview(
        _actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG, days=90
    )

    assert preview.days == 90
    assert preview.affected == 4
    assert audit_rows.deleted_at_cutoffs == []


async def test_purging_removes_only_what_is_past_the_window_and_audits_the_count() -> None:
    audit_rows = _rows_spanning_a_year()
    use_case, _, usage_rows, _, trail = _build(audit=audit_rows, usage=_rows_spanning_a_year())

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
    use_case, audit_rows, *_ = _build(policies=policies, audit=_rows_spanning_a_year())
    actor = _actor(Scope.RETENTION_WRITE)

    outcome = await use_case.purge(actor, RetentionDataset.AUDIT_LOG, days=90)

    assert outcome.deleted == 4
    assert policies.stored == {}, "a one-off purge is not a policy change"


async def test_a_purge_narrower_than_the_floor_is_refused() -> None:
    use_case, audit_rows, *_ = _build(audit=_rows_spanning_a_year())

    with pytest.raises(RetentionWindowTooShortError):
        await use_case.purge(_actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG, days=1)

    assert audit_rows.deleted_at_cutoffs == []


async def test_the_sweep_applies_every_stored_policy_and_needs_no_actor() -> None:
    """It runs on a timer inside the admin application, so there is nobody to
    authorise. That is why it is a separate method rather than `purge` with a
    null actor threaded past the scope check."""
    policies = FakePolicies([RetentionPolicy(dataset=RetentionDataset.USAGE_RECORDS, days=90)])
    use_case, audit_rows, usage_rows, _, _ = _build(
        policies=policies, audit=_rows_spanning_a_year(), usage=_rows_spanning_a_year()
    )

    outcomes = {o.dataset: o.deleted for o in await use_case.purge_due()}

    # audit_log is on the default 360; usage_records was set to 90.
    assert outcomes == {
        RetentionDataset.AUDIT_LOG: 2,
        RetentionDataset.USAGE_RECORDS: 4,
        RetentionDataset.PROMPT_LOGS: 0,
        RetentionDataset.REFUSALS: 0,
    }
    assert len(audit_rows.ats) == 3
    assert len(usage_rows.ats) == 1


async def test_the_sweep_reports_zero_rather_than_skipping_an_empty_dataset() -> None:
    # So one log line can describe a whole sweep.
    use_case, *_ = _build()

    outcomes = await use_case.purge_due()

    assert [o.deleted for o in outcomes] == [0, 0, 0, 0]
    assert {o.dataset for o in outcomes} == set(RetentionDataset)


async def test_a_missing_purge_is_refused_at_construction() -> None:
    """At build time, not at the KeyError a sweep would raise hours later.

    `purge_due` walks every dataset in the enum, so a dataset with no purge
    registered does not merely go unswept — it aborts the sweep, taking the
    datasets that *were* wired with it, and the loop's own handler logs one
    `retention_sweep_failed` that names none of this. Adding a dataset means
    adding a purge, and the two live in different files.
    """
    with pytest.raises(ValueError, match="prompt_logs"):
        ManageRetention(
            policies=FakePolicies(),
            purges={
                RetentionDataset.AUDIT_LOG: FakePurge([]),
                RetentionDataset.USAGE_RECORDS: FakePurge([]),
            },
            authz=_AUTHZ,
            audit=FakeAudit(),
            clock=FakeClock(),
        )


def test_every_dataset_ships_its_bounds_to_the_screen() -> None:
    """The screen used to carry its own copy of the bounds table, and adding a
    fourth dataset broke it: the frontend's closed enum of three meant every
    policy failed to parse behind the one unrecognised value, so the page
    showed nothing at all. The bounds ride on the response now, which is only
    true while every dataset has some — and `RETENTION_BOUNDS` is total, so the
    thing worth pinning is that the response actually carries them.
    """
    from app.interfaces.http.schemas.admin_schemas import RetentionPolicyResponse

    for dataset in RetentionDataset:
        response = RetentionPolicyResponse.of(RetentionPolicy(dataset=dataset, days=30))
        bounds = bounds_for(dataset)

        assert response.dataset == dataset.value
        assert response.minimum_days == bounds.minimum_days
        assert response.maximum_days == bounds.maximum_days
        assert response.maximum_days is None or response.maximum_days >= response.minimum_days
