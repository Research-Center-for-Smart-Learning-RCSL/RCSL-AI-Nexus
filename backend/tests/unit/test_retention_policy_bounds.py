from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.entities.actor import Scope
from app.domain.entities.retention import (
    DEFAULT_PROMPT_LOG_RETENTION_DAYS,
    DEFAULT_RETENTION_DAYS,
    MAXIMUM_PROMPT_LOG_RETENTION_DAYS,
    MINIMUM_RETENTION_DAYS,
    RetentionDataset,
    RetentionPolicy,
)
from app.domain.exceptions import (
    NotAuthorizedError,
    RetentionWindowTooLongError,
    RetentionWindowTooShortError,
)
from tests.unit.manage_retention_fixtures import (
    NOW,
    FakePolicies,
    FakePurge,
    _actor,
    _build,
)

pytest_plugins = ("tests.unit.manage_retention_fixtures",)


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
