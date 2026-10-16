"""Audited offline knowledge recovery; run with --help for the operator contract."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.knowledge_epochs import PostgresKnowledgeEpochs
from app.adapters.persistence.repositories import (
    PostgresKnowledgeRepository,
    PostgresUserRepository,
)
from app.adapters.persistence.sqlalchemy_models import AuditLogRow
from app.adapters.persistence.sqlalchemy_models.knowledge import (
    KnowledgeCollectionRow,
    KnowledgeTenantEpochRow,
)
from app.adapters.storage.filesystem_documents import FilesystemDocumentStorage
from app.application.use_cases.embed_texts import TextEmbedderPort, embedding_identity
from app.domain.entities.actor import Actor, Role
from app.domain.entities.audit import AuditAction
from app.domain.entities.knowledge import DocumentChunk, DocumentStatus, KnowledgeDocument
from app.domain.services.chunking import chunk_text
from app.infrastructure.config import get_settings
from app.infrastructure.db import dispose_engine, get_session_factory, init_engine
from app.infrastructure.di.knowledge import build_vector_store
from app.infrastructure.di.shared import build_runtimes
from app.infrastructure.jobs import _DetachedEmbedder


async def transition(
    sessions: async_sessionmaker[AsyncSession],
    actor: Actor,
    expected_epoch: int,
    reason: str,
    *,
    writers_stopped: bool,
    begin_rebuild: bool = False,
    verified_identity: str | None = None,
) -> int:
    """CAS plus atomic audit. No clock/TTL can declare a writer finished.

    The operator must stop all writers and confirm outstanding vector requests
    have terminated. An epoch mismatch refuses stale recovery instructions.
    Begin/End and this action take collection locks before the tenant lock.
    """
    if (
        actor.role not in (Role.ADMIN, Role.TENANT_ADMIN)
        or not writers_stopped
        or not reason.strip()
    ):
        raise ValueError("active administrator, stopped writers and audit reason required")
    async with sessions() as session:
        collections = list(
            await session.scalars(
                select(KnowledgeCollectionRow)
                .where(KnowledgeCollectionRow.tenant_id == actor.tenant_id)
                .order_by(KnowledgeCollectionRow.id)
                .with_for_update()
            )
        )
        tenant = await session.scalar(
            select(KnowledgeTenantEpochRow)
            .where(KnowledgeTenantEpochRow.tenant_id == actor.tenant_id)
            .with_for_update()
        )
        if tenant is None or tenant.epoch != expected_epoch:
            raise ValueError("knowledge epoch changed; inspect status before recovery")
        if tenant.index_rebuilding and not begin_rebuild and verified_identity is None:
            raise ValueError("interrupted rebuild must be resumed with rebuild, not recover")
        old_dirty = tenant.mutations_in_progress
        tenant.epoch += 1
        tenant.mutations_in_progress = old_dirty + 1 if begin_rebuild else 0
        for collection in collections:
            collection.epoch += 1
            collection.mutations_in_progress = (
                collection.mutations_in_progress + 1 if begin_rebuild else 0
            )
        if begin_rebuild:
            tenant.index_requires_rebuild = True
            tenant.index_rebuilding = True
        elif verified_identity is not None:
            tenant.embedding_identity = verified_identity
            tenant.index_requires_rebuild = False
            tenant.index_rebuilding = False
        session.add(
            AuditLogRow(
                id=str(uuid.uuid4()),
                tenant_id=actor.tenant_id,
                actor_id=actor.id,
                actor_display=actor.display,
                actor_source=actor.source,
                action=str(
                    AuditAction.KNOWLEDGE_REBUILD_STARTED
                    if begin_rebuild
                    else AuditAction.KNOWLEDGE_RECOVERED
                ),
                target=actor.tenant_id,
                outcome="success",
                at=datetime.now(UTC),
                detail={
                    "reason": reason[:512],
                    "previous_epoch": expected_epoch,
                    "previous_dirty": old_dirty,
                    "writers_stopped": True,
                    "verified_rebuild": verified_identity is not None,
                },
            )
        )
        await session.commit()
        return tenant.epoch


async def rebuild(
    sessions: async_sessionmaker[AsyncSession],
    actor: Actor,
    expected_epoch: int,
    reason: str,
    *,
    writers_stopped: bool,
    embedder: TextEmbedderPort,
) -> int:
    # A transaction-scoped lock survives the short commits made by the worker
    # and releases on crashes. It prevents two recovery CLIs rebuilding at once.
    async with sessions() as lock:
        acquired = await lock.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:tenant, 56))"),
            {"tenant": actor.tenant_id},
        )
        if not acquired:
            raise ValueError("a tenant rebuild is already running")
        return await _rebuild(
            sessions,
            actor,
            expected_epoch,
            reason,
            writers_stopped=writers_stopped,
            embedder=embedder,
        )


async def _rebuild(
    sessions: async_sessionmaker[AsyncSession],
    actor: Actor,
    expected_epoch: int,
    reason: str,
    *,
    writers_stopped: bool,
    embedder: TextEmbedderPort,
) -> int:
    """Rebuild every document from stored text; failure leaves replay fenced.

    Preflight all source text before deleting anything, then re-read one
    document at a time to avoid retaining the tenant corpus in memory.
    """
    settings = get_settings()
    storage = FilesystemDocumentStorage(settings.document_storage_path, actor.tenant_id)
    vectors = build_vector_store(settings, actor.tenant_id)
    target, runtime = await embedder.resolve()
    identity = embedding_identity(target)
    if identity is None:
        raise ValueError("rebuild requires an exact embedding manifest")
    documents: list[KnowledgeDocument] = []
    async with sessions() as session:
        repo = PostgresKnowledgeRepository(session, actor.tenant_id)
        while page := await repo.list_documents(limit=100, offset=len(documents)):
            documents.extend(page)
    for document in documents:
        await storage.read_text(document.id)
    epoch = await transition(
        sessions, actor, expected_epoch, reason, writers_stopped=writers_stopped, begin_rebuild=True
    )
    await vectors.reset_index()
    for document in documents:
        chunks = chunk_text(await storage.read_text(document.id))
        if chunks:
            embeddings = await embedder.embed_with(
                runtime, [c.text for c in chunks], target.ref, expected_identity=identity
            )
            await vectors.ensure_ready(len(embeddings[0]))
            await vectors.upsert(
                [
                    DocumentChunk(document.id, document.collection_id, c.index, c.text, v)
                    for c, v in zip(chunks, embeddings, strict=True)
                ]
            )
        async with sessions() as session:
            await PostgresKnowledgeRepository(session, actor.tenant_id).set_document_status(
                document.id, DocumentStatus.INDEXED, chunk_count=len(chunks)
            )
            await session.commit()
    return await transition(
        sessions, actor, epoch, reason, writers_stopped=writers_stopped, verified_identity=identity
    )


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    init_engine(settings)
    try:
        sessions = get_session_factory()
        async with sessions() as session:
            user = await PostgresUserRepository.unscoped(session).get_by_login(args.actor)
        if (
            user is None
            or user.disabled_at is not None
            or user.role not in (Role.ADMIN, Role.TENANT_ADMIN)
        ):
            raise ValueError("an active administrator account is required")
        actor = Actor(
            user.id,
            user.login,
            user.role,
            "local",
            RoleAuthorization().scopes_for(user.role.value),
            tenant_id=user.tenant_id,
        )
        if args.action == "status":
            current = await PostgresKnowledgeEpochs(sessions, actor.tenant_id).read(None)
            print(json.dumps(asdict(current) if current else None))
            return
        if args.expected_epoch is None or not args.writers_stopped or not args.reason:
            raise ValueError("--expected-epoch, --writers-stopped and --reason are required")
        if args.action == "rebuild":
            epoch = await rebuild(
                sessions,
                actor,
                args.expected_epoch,
                args.reason,
                writers_stopped=True,
                embedder=_DetachedEmbedder(build_runtimes(settings)),
            )
        else:
            epoch = await transition(
                sessions, actor, args.expected_epoch, args.reason, writers_stopped=True
            )
        print(json.dumps({"tenant_id": actor.tenant_id, "epoch": epoch, "action": args.action}))
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "recover", "rebuild"))
    parser.add_argument("--actor", required=True, help="active administrator login; scopes tenant")
    parser.add_argument("--expected-epoch", type=int)
    parser.add_argument("--reason", help="audited recovery reason, without document content")
    parser.add_argument(
        "--writers-stopped",
        action="store_true",
        help="confirm all entrances/jobs stopped and vector writes terminated",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
