"""Dependency providers for knowledge."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.http.parser_client import HttpDocumentParser
from app.adapters.persistence.document_state import DocumentStateCommitter
from app.adapters.persistence.repositories import (
    PostgresKnowledgeRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresPromptTemplateRepository,
    PostgresRoutingPolicyRepository,
)
from app.adapters.storage.filesystem_documents import FilesystemDocumentStorage
from app.adapters.vector.qdrant_store import QdrantVectorStore
from app.application.use_cases.apply_prompt_template import ApplyPromptTemplate
from app.application.use_cases.embed_texts import EmbedTexts
from app.application.use_cases.ground_chat import GroundChat
from app.application.use_cases.ingest_document import IngestDocument
from app.application.use_cases.manage_knowledge import ManageKnowledge
from app.application.use_cases.manage_prompt_templates import ManagePromptTemplates
from app.application.use_cases.search_knowledge import SearchKnowledge
from app.domain.entities.model import RuntimeKind
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.services.routing_service import RoutingService
from app.infrastructure.config import Settings
from app.infrastructure.db import get_session_factory
from app.shared.clock import SystemClock

from .shared import SessionDep, SettingsDep, TenantIdDep


def build_manage_knowledge(
    request: Request, session: SessionDep, settings: SettingsDep, tenant: TenantIdDep
) -> ManageKnowledge:
    """Both collaborators are scoped to the actor's tenant, and that is the whole
    of the knowledge base's isolation.

    The repository filters and stamps by tenant; the storage adapter puts the
    tenant in the path. Neither takes it as an argument, so `ManageKnowledge`
    names no tenant anywhere and cannot read or write another one's documents.
    See docs/architecture/security.md section 7.3.
    """
    return ManageKnowledge(
        knowledge=PostgresKnowledgeRepository(session, tenant),
        storage=FilesystemDocumentStorage(settings.document_storage_path, tenant),
        vectors=build_vector_store(settings, tenant),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_vector_store(settings: Settings, tenant_id: str) -> QdrantVectorStore:
    """Scoped to the tenant, like the repository and the document storage. The
    tenant names the collection as well as the payload filter, so a search that
    lost it asks for a collection that does not exist rather than reading
    everyone's passages; see adapters/vector/qdrant_store.py."""
    return QdrantVectorStore(
        settings.qdrant_base_url,
        settings.qdrant_api_key,
        tenant_id,
        timeout_seconds=settings.qdrant_timeout_seconds,
    )


def build_embed_texts(
    runtimes: dict[RuntimeKind, ModelRuntimePort], session: AsyncSession
) -> EmbedTexts:
    """Resolves the `embedding` capability through the same routing policy,
    registry and node table the chat path uses, so there is one mechanism for
    naming a model rather than a second setting that could disagree with it.

    Takes the runtimes and the session as plain arguments rather than a
    `Request`, because the detached ingestion task has an app but no request and
    opens a session of its own for each resolve (infrastructure/jobs.py).
    """
    return EmbedTexts(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        runtimes=runtimes,
        routing=RoutingService(),
    )


def build_ingest_document(
    request: Request, session: SessionDep, settings: SettingsDep, tenant: TenantIdDep
) -> IngestDocument:
    """The state committer holds no request session: `claim` writes through its
    own transaction, so the state change survives whatever the request does
    next, and `run` is scheduled detached with the same construction (jobs.py).
    The embedder does use the request session, because only `run` embeds and it
    is constructed separately there."""
    return IngestDocument(
        state_committer=DocumentStateCommitter(get_session_factory(), tenant),
        storage=FilesystemDocumentStorage(settings.document_storage_path, tenant),
        parser=HttpDocumentParser(settings.parser_base_url, settings.parser_timeout_seconds),
        jobs=request.app.state.jobs,
        vectors=build_vector_store(settings, tenant),
        embedder=build_embed_texts(request.app.state.runtimes, session),
        # `claim` alone uses this, and it must be the request session: the row
        # it claims was inserted in that same uncommitted transaction. See
        # IngestDocument.claim.
        knowledge=PostgresKnowledgeRepository(session, tenant),
    )


def build_ground_chat_factory(
    request: Request, session: SessionDep, settings: SettingsDep
) -> Callable[[str], GroundChat]:
    """A factory, not a `GroundChat`, and the reason is which entrances use it.

    Every other tenant-scoped builder here depends on `current_tenant_id`, which
    reads `current_actor`. The gateway installs no such resolver: it
    authenticates an API key through `authenticate_api_key`, so depending on
    `current_actor` there raises at request time rather than at wiring time.
    Taking the tenant as an argument lets the chat routers pass the tenant of
    whichever actor they already resolved, which is the same value either way.

    The gateway's vector store is then built from the read-only Qdrant key
    mounted at the same target name (docker-compose.yml), so retrieving a
    passage to answer a request cannot become writing one, the same split its
    database account has.
    """

    def make(tenant_id: str) -> GroundChat:
        return GroundChat(
            search=SearchKnowledge(
                vectors=build_vector_store(settings, tenant_id),
                embedder=build_embed_texts(request.app.state.runtimes, session),
                authz=request.app.state.authz,
            )
        )

    return make


GroundChatFactoryDep = Annotated[Callable[[str], GroundChat], Depends(build_ground_chat_factory)]


def build_manage_prompt_templates(
    request: Request, session: SessionDep, tenant: TenantIdDep
) -> ManagePromptTemplates:
    """Scoped, so a template is authored into, listed from and deleted within
    the caller's own tenant, decided here rather than by anything the caller
    sends."""
    return ManagePromptTemplates(
        templates=PostgresPromptTemplateRepository(session, tenant),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
        clock=SystemClock(),
        tenant_id=tenant,
    )


def build_apply_prompt_template_factory(
    request: Request, session: SessionDep
) -> Callable[[str], ApplyPromptTemplate]:
    """A factory, for the reason `build_ground_chat_factory` gives at length:
    the gateway installs no `current_actor` resolver, so a builder depending on
    `TenantIdDep` raises at request time there rather than failing at wiring
    time. The chat routers pass the tenant of the actor they already resolved,
    which is the same value either way."""

    def make(tenant_id: str) -> ApplyPromptTemplate:
        return ApplyPromptTemplate(
            templates=PostgresPromptTemplateRepository(session, tenant_id),
            authz=request.app.state.authz,
        )

    return make


ApplyPromptTemplateFactoryDep = Annotated[
    Callable[[str], ApplyPromptTemplate], Depends(build_apply_prompt_template_factory)
]


def build_search_knowledge(
    request: Request, session: SessionDep, settings: SettingsDep, tenant: TenantIdDep
) -> SearchKnowledge:
    return SearchKnowledge(
        vectors=build_vector_store(settings, tenant),
        embedder=build_embed_texts(request.app.state.runtimes, session),
        authz=request.app.state.authz,
    )
