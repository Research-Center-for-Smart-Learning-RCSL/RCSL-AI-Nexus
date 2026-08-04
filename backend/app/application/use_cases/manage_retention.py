"""Reading and setting how long records are kept, and deleting them.

Three operations behind one scope. `retention:write` is admin-only, and the
reason it covers the read as well is that the number is of no interest to
anyone who cannot change it — see `ADMIN_ONLY_SCOPES`.

The sweep that applies a policy on a schedule calls `purge_due` with no actor,
which is the one path here that checks no scope, because there is nobody to
check: it runs on a timer inside the admin application. It is a separate method
rather than an actor of `None` threaded through `purge`, so that "no scope
check" is a decision visible at the call site instead of a null slipping past
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.retention import (
    DEFAULT_RETENTION_DAYS,
    MINIMUM_RETENTION_DAYS,
    PurgeOutcome,
    RetentionDataset,
    RetentionPolicy,
)
from app.domain.exceptions import RetentionWindowTooShortError
from app.domain.ports.repositories import RecordPurgePort, RetentionPolicyRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class RetentionPreview:
    """What a purge would remove, asked before removing it.

    A separate read rather than a dry-run flag on `purge`, because a dry run
    sharing a code path with the real thing is one edit away from deleting
    during a preview.
    """

    dataset: RetentionDataset
    days: int
    affected: int


class ManageRetention:
    def __init__(
        self,
        policies: RetentionPolicyRepositoryPort,
        purges: dict[RetentionDataset, RecordPurgePort],
        authz: AuthorizationPort,
        audit: AuditPort,
        clock: Clock,
    ) -> None:
        self._policies = policies
        self._purges = purges
        self._authz = authz
        self._audit = audit
        self._clock = clock

    async def list_policies(self, actor: Actor) -> list[RetentionPolicy]:
        """Every dataset, with the default filled in where nothing is stored.

        Built from the enum rather than from the rows, so a dataset that has
        never been configured still appears with the number that governs it. A
        screen listing only stored rows would show nothing at all on a fresh
        deployment and imply that nothing expires.
        """
        self._authz.require(actor, Scope.RETENTION_WRITE)
        stored = {p.dataset: p for p in await self._policies.list_policies()}
        return [
            stored.get(dataset, RetentionPolicy(dataset=dataset, days=DEFAULT_RETENTION_DAYS))
            for dataset in RetentionDataset
        ]

    async def set_policy(
        self, actor: Actor, dataset: RetentionDataset, days: int
    ) -> RetentionPolicy:
        self._authz.require(actor, Scope.RETENTION_WRITE)
        if days < MINIMUM_RETENTION_DAYS:
            # Refused rather than clamped. Clamping would store a number the
            # administrator did not choose and report success, and the gap
            # between what they typed and what governs is exactly the kind of
            # thing nobody re-reads.
            raise RetentionWindowTooShortError(
                detail=f"retention must be at least {MINIMUM_RETENTION_DAYS} days, got {days}"
            )

        policy = RetentionPolicy(
            dataset=dataset,
            days=days,
            updated_at=self._clock.now(),
            updated_by=actor.display,
        )
        await self._policies.set_policy(policy)
        await self._audit.record(
            actor=actor,
            action="retention.policy_set",
            target=dataset.value,
            outcome="success",
            detail={"days": str(days)},
        )
        return policy

    async def preview(
        self, actor: Actor, dataset: RetentionDataset, days: int | None = None
    ) -> RetentionPreview:
        """How many rows the policy — or a proposed one — would remove now.

        `days` is optional so the screen can answer "what would happen if I
        saved this" before saving it. A change that turns out to delete four
        years of audit history is worth learning about from a number on the
        form rather than from the result.
        """
        self._authz.require(actor, Scope.RETENTION_WRITE)
        effective = days if days is not None else await self._days_for(dataset)
        affected = await self._purges[dataset].count_older_than(self._cutoff(effective))
        return RetentionPreview(dataset=dataset, days=effective, affected=affected)

    async def purge(
        self, actor: Actor, dataset: RetentionDataset, days: int | None = None
    ) -> PurgeOutcome:
        """Delete now, either to the stored policy or to a tighter window.

        The audit entry is written **after** the delete and records the cutoff
        and the count, because the count is the part nobody can reconstruct
        afterwards — least of all from the table it came out of.

        Under the retention policy chosen for this platform that entry is
        itself deletable by a later purge of `audit_log`. That is the accepted
        consequence of allowing audit records to be purged at all; it is
        recorded in `security.md` §12.1 rather than worked around here.
        """
        self._authz.require(actor, Scope.RETENTION_WRITE)
        effective = days if days is not None else await self._days_for(dataset)
        if effective < MINIMUM_RETENTION_DAYS:
            raise RetentionWindowTooShortError(
                detail=(
                    f"purge window must be at least {MINIMUM_RETENTION_DAYS} days,"
                    f" got {effective}"
                )
            )

        cutoff = self._cutoff(effective)
        deleted = await self._purges[dataset].delete_older_than(cutoff)
        await self._audit.record(
            actor=actor,
            action="retention.purged",
            target=dataset.value,
            outcome="success",
            detail={
                "days": str(effective),
                "cutoff": cutoff.isoformat(),
                "deleted": str(deleted),
            },
        )
        return PurgeOutcome(dataset=dataset, cutoff=cutoff, deleted=deleted)

    async def purge_due(self) -> list[PurgeOutcome]:
        """Apply every stored policy. Called by the scheduled sweep, not by a
        request, which is why it takes no actor and checks no scope.

        Datasets with nothing to delete produce an outcome of zero rather than
        being skipped, so the caller can log one line describing a whole sweep.
        """
        outcomes: list[PurgeOutcome] = []
        for dataset in RetentionDataset:
            cutoff = self._cutoff(await self._days_for(dataset))
            deleted = await self._purges[dataset].delete_older_than(cutoff)
            outcomes.append(PurgeOutcome(dataset=dataset, cutoff=cutoff, deleted=deleted))
        return outcomes

    async def _days_for(self, dataset: RetentionDataset) -> int:
        policy = await self._policies.get_policy(dataset)
        return policy.days if policy else DEFAULT_RETENTION_DAYS

    def _cutoff(self, days: int) -> datetime:
        return self._clock.now() - timedelta(days=days)
