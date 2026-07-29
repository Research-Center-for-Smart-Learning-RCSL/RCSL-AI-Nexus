"""Scheduling work that outlives the request that asked for it.

A model pull is tens of gigabytes. It cannot run inside the request, and it
cannot use the request's database session, which is closed the moment the
response is sent.

**The task holds no session across the pull.** `DownloadModel.run` reads the
model and writes its final state through a `ModelStateCommitter`, each in its
own short transaction, and progress goes to the cache in between. An earlier
version wrapped the whole `run` in one `session_scope`, which pinned a
connection idle-in-transaction for the whole download and held the database's
VACUUM horizon back for hours.

The dependencies are handed in from `app.state` rather than read from a module
global, for the reason `di.py` gives: process singletons live there so a test
can build an application with different wiring without it leaking into the
next one.

**A task started here does not survive a restart.** That is accepted rather
than solved: a durable queue would be a second piece of infrastructure to run
and monitor, for one operation. What makes it acceptable is that progress is
kept in the cache, so an interrupted download is visibly stuck rather than
silently gone, and the deploy-time reconciliation in provision.py moves a
model the crash left mid-pull out of `downloading`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any, cast

from fastapi import FastAPI

from app.adapters.http.parser_client import HttpDocumentParser
from app.adapters.persistence.document_state import DocumentStateCommitter
from app.adapters.persistence.model_state import ModelStateCommitter
from app.adapters.storage.filesystem_documents import FilesystemDocumentStorage
from app.application.use_cases.download_model import DownloadModel
from app.application.use_cases.ingest_document import IngestDocument
from app.domain.entities.model import Model, RuntimeKind
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import ModelRepositoryPort
from app.infrastructure.config import get_settings
from app.infrastructure.db import get_session_factory, session_scope
from app.infrastructure.di import build_embed_texts, build_vector_store

logger = logging.getLogger(__name__)

_running: set[asyncio.Task[Any]] = set()
"""Strong references to in-flight tasks.

`asyncio` keeps only weak ones, so a task nobody holds can be collected
mid-await and the download stops with nothing logged anywhere. This is
documented behaviour of `create_task`, and this set is the documented remedy.
"""


def schedule_download(app: FastAPI, *, model_id: str, job_id: str) -> None:
    task = asyncio.create_task(_run_download(app, model_id, job_id), name=f"download:{job_id}")
    _running.add(task)
    task.add_done_callback(_running.discard)


def schedule_ingestion(app: FastAPI, *, document_id: str, job_id: str, tenant_id: str) -> None:
    """The tenant travels with the task.

    It is taken from the actor in the request that scheduled this, not looked up
    later, so the detached write lands under the same tenant the upload did. A
    background task is exactly where a scoped repository would otherwise be
    constructed from nothing.
    """
    task = asyncio.create_task(
        _run_ingestion(app, document_id, job_id, tenant_id), name=f"ingest:{job_id}"
    )
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _run_download(app: FastAPI, model_id: str, job_id: str) -> None:
    """Never raises. `run` writes every outcome to the job and to the model
    state through short transactions of its own; the guard here is only for a
    failure to construct or schedule at all."""
    try:
        # `run` reads and writes through the state committer's short
        # transactions and never touches the request-session repository, so
        # `models` is passed None here. `start` (in the request) is the only
        # caller that uses it, and it is built separately with a real session.
        committer = ModelStateCommitter(get_session_factory())
        await DownloadModel(
            models=cast("ModelRepositoryPort", None),
            runtimes=app.state.runtimes,
            jobs=app.state.jobs,
            state_committer=committer,
            authz=app.state.authz,
            audit=app.state.audit,
        ).run(model_id, job_id)
    except Exception:
        logger.exception("download_task_failed model=%s job=%s", model_id, job_id)


class _DetachedEmbedder:
    """`TextEmbedderPort` that holds no session between calls.

    `resolve` opens a short transaction to read the routing policy, the registry
    and the node table, and closes it before returning; `embed_with` talks only
    to the runtime adapter and touches no database at all. So a document is
    parsed and embedded without a connection pinned idle-in-transaction for the
    duration, which is the hazard the download job was rewritten to avoid.
    """

    def __init__(self, runtimes: dict[RuntimeKind, ModelRuntimePort]) -> None:
        self._runtimes = runtimes

    async def resolve(self) -> tuple[Model, ModelRuntimePort]:
        async with session_scope() as session:
            return await build_embed_texts(self._runtimes, session).resolve()

    async def embed_with(
        self, runtime: ModelRuntimePort, texts: Sequence[str], ref: str | None = None
    ) -> list[list[float]]:
        if ref is None:
            target, runtime = await self.resolve()
            ref = target.ref
        async with session_scope() as session:
            return await build_embed_texts(self._runtimes, session).embed_with(runtime, texts, ref)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        target, runtime = await self.resolve()
        return await self.embed_with(runtime, texts, target.ref)


async def _run_ingestion(app: FastAPI, document_id: str, job_id: str, tenant_id: str) -> None:
    """Never raises, for the reason `_run_download` does not: `run` writes every
    outcome to the job and to the document's state through its own short
    transactions, and this guard covers only a failure to construct at all."""
    try:
        settings = get_settings()
        await IngestDocument(
            state_committer=DocumentStateCommitter(get_session_factory(), tenant_id),
            storage=FilesystemDocumentStorage(settings.document_storage_path, tenant_id),
            parser=HttpDocumentParser(settings.parser_base_url, settings.parser_timeout_seconds),
            jobs=app.state.jobs,
            vectors=build_vector_store(settings, tenant_id),
            embedder=_DetachedEmbedder(app.state.runtimes),
        ).run(document_id, job_id)
    except Exception:
        logger.exception("ingestion_task_failed document=%s job=%s", document_id, job_id)
