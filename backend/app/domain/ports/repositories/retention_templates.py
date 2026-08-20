"""Persistence retention templates boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.entities.prompt_template import PromptTemplate
from app.domain.entities.retention import RetentionDataset, RetentionPolicy


class RecordPurgePort(Protocol):
    """Counting and deleting rows older than a cutoff, for retention.

    One protocol implemented by both the audit and usage repositories, so the
    retention use case holds a mapping of dataset to port and gains no `if` per
    table. Adding a third dataset is then a repository that satisfies this and
    an entry in that mapping.

    `count_older_than` exists so the screen can say what a purge would remove
    before it removes it. It is deliberately a separate call rather than a dry
    run: a dry run that shares a code path with the real thing is one edit away
    from deleting during a preview.

    **Unscoped by tenant, unlike every other repository here.** Retention is a
    platform-wide policy held by an administrator who is not confined to a
    tenant, and a purge that silently spared other tenants' rows would report a
    number that did not match what it did. The scope check is in the use case,
    where `retention:write` is admin-only.
    """

    async def count_older_than(self, cutoff: datetime) -> int: ...

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Returns the number of rows removed."""
        ...


class RetentionPolicyRepositoryPort(Protocol):
    async def list_policies(self) -> list[RetentionPolicy]:
        """Every dataset, including those never configured.

        The default is filled in by the caller rather than stored at migration
        time, so a dataset added later needs no backfill and the number in the
        code is the number in the absence of a decision.
        """
        ...

    async def get_policy(self, dataset: RetentionDataset) -> RetentionPolicy | None: ...

    async def set_policy(self, policy: RetentionPolicy) -> None:
        """Upsert. The row appears the first time somebody disagrees with the
        default, which is also the first time there is an author to record."""
        ...


class PromptTemplateRepositoryPort(Protocol):
    """Tenant-scoped, like the knowledge repository: the filter is the adapter's
    and comes from the tenant it was constructed with, never from a caller."""

    async def get(self, template_id: str) -> PromptTemplate | None: ...

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        """How a chat request resolves `"prompt_template": "code-review"`.

        Scoped, so the name a caller writes can only ever name their own
        tenant's template — which is what makes selection a choice among
        trusted values rather than a way to reach somebody else's text.
        """
        ...

    async def list_all(self) -> list[PromptTemplate]: ...

    async def save(self, template: PromptTemplate) -> None: ...

    async def delete(self, template_id: str) -> None: ...
