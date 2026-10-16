"""The recovery CLI's pre-destructive checks: tenant guard and rebuild selection."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.entities.actor import Role
from app.domain.entities.knowledge import DocumentStatus, KnowledgeDocument
from app.domain.entities.user import User
from app.infrastructure.recover_knowledge import checked_actor, plan_rebuild

ADMIN = User("u1", "admin", "Admin", Role.TENANT_ADMIN, tenant_id="tenant-a")


def test_actor_is_accepted_only_for_its_own_tenant():
    actor = checked_actor(ADMIN, "tenant-a")
    assert actor.tenant_id == "tenant-a" and actor.id == "u1"


@pytest.mark.parametrize(
    "user",
    [
        None,
        replace(ADMIN, tenant_id="tenant-b"),
        replace(ADMIN, role=Role.USER),
        replace(ADMIN, disabled_at=datetime.now(UTC)),
    ],
)
def test_actor_is_refused_for_another_tenant_or_without_active_admin(user):
    with pytest.raises(ValueError):
        checked_actor(user, "tenant-a")


def test_rebuild_selects_only_indexed_or_extracted_documents():
    documents = [
        KnowledgeDocument(status.value, "tenant-a", "c", "f.txt", "text/plain", 1, status=status)
        for status in DocumentStatus
    ]
    rebuilt, skipped = plan_rebuild(documents)
    assert {d.status for d in rebuilt} == {DocumentStatus.INDEXED, DocumentStatus.EXTRACTED}
    assert {d.status for d in skipped} == {
        DocumentStatus.UPLOADED,
        DocumentStatus.EXTRACTING,
        DocumentStatus.INDEXING,
        DocumentStatus.ERROR,
    }
