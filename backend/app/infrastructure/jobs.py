"""Scheduling work that outlives the request that asked for it.

A model pull is tens of gigabytes. It cannot run inside the request, and it
cannot use the request's database session, which is closed the moment the
response is sent. So the task gets a session of its own from the same factory
the application uses, and this module is the composition root for it.

The other dependencies are handed in by the caller rather than read from a
module global, for the reason `di.py` gives: process singletons live on
`app.state` so a test can build an application with different wiring without
it leaking into the next one. Everything passed here outlives the request; the
session is the only thing that does not, which is why it is the only thing
built inside the task.

**A task started here does not survive a restart.** That is accepted rather
than solved: a durable queue would be a second piece of infrastructure to run
and monitor, for one operation. What makes it acceptable is that progress is
kept in the cache, so an interrupted download is visibly stuck rather than
silently gone, and the model is left in a state a later attempt can retake.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI

from app.adapters.persistence.repositories import PostgresModelRepository
from app.application.use_cases.download_model import DownloadModel
from app.infrastructure.db import session_scope

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
    """Owns its transaction, and never raises.

    A background task that raises has nowhere to report to, so the use case
    writes every outcome to the job and to the model state instead. The guard
    here is for the one thing it cannot reach: a failure to open the session
    in the first place, which would otherwise leave the model stuck in
    `downloading` with no record of why.
    """
    try:
        async with session_scope() as session:
            await DownloadModel(
                models=PostgresModelRepository(session),
                runtimes=app.state.runtimes,
                jobs=app.state.jobs,
                authz=app.state.authz,
                audit=app.state.audit,
            ).run(model_id, job_id)
    except Exception:
        logger.exception("download_task_failed model=%s job=%s", model_id, job_id)
