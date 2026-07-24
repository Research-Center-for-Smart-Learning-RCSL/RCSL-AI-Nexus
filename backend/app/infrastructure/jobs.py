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
from typing import Any, cast

from fastapi import FastAPI

from app.adapters.persistence.model_state import ModelStateCommitter
from app.application.use_cases.download_model import DownloadModel
from app.domain.ports.repositories import ModelRepositoryPort
from app.infrastructure.db import get_session_factory

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
