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
    DEFAULT_PROMPT_LOG_RETENTION_DAYS,
    DEFAULT_RETENTION_DAYS,
    MAXIMUM_PROMPT_LOG_RETENTION_DAYS,
    MINIMUM_RETENTION_DAYS,
    RetentionDataset,
    RetentionPolicy,
    bounds_for,
)
from app.domain.exceptions import (
    NotAuthorizedError,
    RetentionWindowTooLongError,
    RetentionWindowTooShortError,
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
    # Not one number any more. `prompt_logs` defaults markedly shorter than the
    # two metadata datasets, which is section 9.2's requirement made a value
    # rather than a convention.
    by_dataset = {p.dataset: p.days for p in policies}
    assert by_dataset[RetentionDataset.AUDIT_LOG] == DEFAULT_RETENTION_DAYS
    assert by_dataset[RetentionDataset.USAGE_RECORDS] == DEFAULT_RETENTION_DAYS
    assert by_dataset[RetentionDataset.PROMPT_LOGS] == DEFAULT_PROMPT_LOG_RETENTION_DAYS
    assert DEFAULT_PROMPT_LOG_RETENTION_DAYS < DEFAULT_RETENTION_DAYS
    assert all(p.updated_by is None for p in policies)


async def test_setting_a_window_records_who_set_it_and_audits_the_change() -> None:
    use_case, _, _, _, trail = _build()

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

    stored = {p.dataset: p.days for p in await use_case.list_policies(actor)}
    assert stored[RetentionDataset.AUDIT_LOG] == DEFAULT_RETENTION_DAYS


async def test_a_prompt_log_window_over_the_ceiling_is_refused() -> None:
    """The bound that runs the other way, and the reason this dataset needed
    its own.

    For `audit_log` the danger is a window set too short — a week of history is
    too little to investigate anything reported late. For transcripts it is a
    window set too long: they hold the message content section 9.2 keeps out of
    the ordinary logs, and the failure the whole control was designed against is
    full logging switched on for an afternoon and left on for a year. The old
    360-day default would have reproduced exactly that, with an administrator
    who believed they had configured something.
    """
    use_case, *_ = _build()
    actor = _actor(Scope.RETENTION_WRITE)

    with pytest.raises(RetentionWindowTooLongError):
        await use_case.set_policy(
            actor, RetentionDataset.PROMPT_LOGS, MAXIMUM_PROMPT_LOG_RETENTION_DAYS + 1
        )

    stored = {p.dataset: p.days for p in await use_case.list_policies(actor)}
    assert stored[RetentionDataset.PROMPT_LOGS] == DEFAULT_PROMPT_LOG_RETENTION_DAYS


async def test_the_metadata_datasets_have_no_ceiling() -> None:
    """The mirror assertion, so the two shapes cannot quietly converge. An
    administrator may keep audit history for as long as they care to; what is
    bounded there is growth, not disclosure."""
    use_case, *_ = _build()

    policy = await use_case.set_policy(
        _actor(Scope.RETENTION_WRITE), RetentionDataset.AUDIT_LOG, 3650
    )

    assert policy.days == 3650


async def test_a_window_below_the_prompt_log_floor_is_refused_too() -> None:
    """Not the interesting bound, but a real one: zero would mean the sweep
    deleting a transcript in the same hour somebody opened the window to read
    it."""
    use_case, *_ = _build()

    with pytest.raises(RetentionWindowTooShortError):
        await use_case.set_policy(_actor(Scope.RETENTION_WRITE), RetentionDataset.PROMPT_LOGS, 0)


async def test_the_listed_number_is_the_one_that_governs_not_the_one_stored() -> None:
    """The screen and the sweep must not disagree.

    `_days_for` clamps a stored row that predates a tightening of the bounds, so
    the sweep deletes at the ceiling. If `list_policies` returned the row
    verbatim, `GET /admin/retention` and the Retention screen would report the
    wider number an administrator once typed while the sweep used the narrower
    one — this docstring's own promise ("the number that governs it") being
    false on the one surface that states it, which is the failure the clamp was
    added to prevent reappearing on the reporting side.
    """
    policies = FakePolicies([RetentionPolicy(dataset=RetentionDataset.PROMPT_LOGS, days=3650)])
    use_case, *_ = _build(policies=policies)

    listed = {p.dataset: p for p in await use_case.list_policies(_actor(Scope.RETENTION_WRITE))}

    governing = listed[RetentionDataset.PROMPT_LOGS]
    assert governing.days == MAXIMUM_PROMPT_LOG_RETENTION_DAYS
    swept = {o.dataset: o for o in await use_case.purge_due()}
    assert swept[RetentionDataset.PROMPT_LOGS].cutoff == NOW - timedelta(days=governing.days), (
        "the screen and the sweep agree, which is the whole assertion"
    )


async def test_clamping_on_read_does_not_erase_who_set_it() -> None:
    """The number changes; the provenance does not. "Set by X on Y" stays true
    and is the context for a value that no longer matches what they typed."""
    policies = FakePolicies(
        [
            RetentionPolicy(
                dataset=RetentionDataset.PROMPT_LOGS,
                days=3650,
                updated_at=NOW,
                updated_by="admin@example.test",
            )
        ]
    )
    use_case, *_ = _build(policies=policies)

    listed = {p.dataset: p for p in await use_case.list_policies(_actor(Scope.RETENTION_WRITE))}

    assert listed[RetentionDataset.PROMPT_LOGS].updated_by == "admin@example.test"
    assert listed[RetentionDataset.PROMPT_LOGS].updated_at == NOW


async def test_a_stored_window_past_a_tightened_ceiling_is_clamped_on_read() -> None:
    """Validating only on the way in would leave an old row governing.

    A policy can predate a tightening of the bounds — `prompt_logs` did not
    exist when this use case was written, and a future ceiling may be lowered
    after somebody set a window under the old one. A row that survives such a
    change and keeps governing is the familiar shape of a control every surface
    reports as in force.
    """
    policies = FakePolicies([RetentionPolicy(dataset=RetentionDataset.PROMPT_LOGS, days=3650)])
    prompt_rows = FakePurge([NOW - timedelta(days=n) for n in (1, 31, 400)])
    use_case, _, _, prompt, _ = _build(policies=policies, prompt=prompt_rows)

    outcomes = {o.dataset: o for o in await use_case.purge_due()}

    swept = outcomes[RetentionDataset.PROMPT_LOGS]
    assert swept.cutoff == NOW - timedelta(days=MAXIMUM_PROMPT_LOG_RETENTION_DAYS)
    assert swept.deleted == 2, "the 3650-day row did not get to keep 400 days of transcripts"
    assert len(prompt.ats) == 1


# --- preview and purge ---------------------------------------------------


def _rows_spanning_a_year() -> FakePurge:
    return FakePurge([NOW - timedelta(days=n) for n in (1, 100, 300, 400, 500)])


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


# --- the scheduled sweep -------------------------------------------------


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
