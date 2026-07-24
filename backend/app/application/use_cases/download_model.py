"""Downloading model weights, as a job rather than a request.

A pull is tens of gigabytes over a link nobody controls. Holding a request
open for it would tie up a worker, hit every timeout between here and the
browser, and give the client no way to report progress or survive a reload.

**The long half runs detached, in its own transaction.** `start` validates and
returns; `run` is scheduled by the composition root with a session of its own,
because the request's session is closed the moment the response is sent. That
detachment is also why progress lives in the cache rather than in memory: if
the process restarts mid-pull the task is gone, and a job that is visibly
stale is far better than one that vanished.

See docs/architecture/security.md section 7.1 for why the reference is
validated rather than interpolated.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import aclosing

from app.application.use_cases.manage_models import ModelStateCommitterPort
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.model import Model, ModelState, RuntimeKind
from app.domain.exceptions import ModelNotFoundError, ModelStateConflictError
from app.domain.ports.infrastructure_ports import JobProgressPort, JobStatus
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import ModelRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 24 * 3600
"""Long enough that a finished download is still explicable the next morning,
short enough that the cache does not accumulate history. The registry holds
the durable outcome in the model's state."""


class DownloadModel:
    def __init__(
        self,
        models: ModelRepositoryPort,
        runtimes: dict[RuntimeKind, ModelRuntimePort],
        jobs: JobProgressPort,
        state_committer: ModelStateCommitterPort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._models = models
        self._runtimes = runtimes
        self._jobs = jobs
        # Used by the detached `run`, which must not hold a session across the
        # pull. `start` and `status` run in the request and keep the request
        # session.
        self._state = state_committer
        self._authz = authz
        self._audit = audit

    async def start(self, actor: Actor, model_id: str) -> JobStatus:
        """Claim the model and publish a queued job.

        The state is written here rather than inside the detached task, so a
        second click cannot start a second pull of the same weights: the
        conflict is decided while the caller is still waiting for an answer.
        """
        self._authz.require(actor, Scope.MODEL_WRITE)
        model = await self._require(model_id)

        if model.state in (ModelState.DOWNLOADING, ModelState.LOADING, ModelState.UNLOADING):
            raise ModelStateConflictError(detail=f"model {model.id} is already {model.state}")
        if model.state is ModelState.LOADED:
            raise ModelStateConflictError(detail=f"model {model.id} is loaded; unload it first")

        await self._models.set_state(model.id, ModelState.DOWNLOADING)

        status = JobStatus(
            job_id=str(uuid.uuid4()), state="queued", target=model.id, message="Queued"
        )
        await self._jobs.set(status, ttl_seconds=JOB_TTL_SECONDS)
        await self._audit.record(
            actor, "model.download_started", target=model.id, detail={"job": status.job_id}
        )
        return status

    async def status(self, actor: Actor, job_id: str) -> JobStatus:
        self._authz.require(actor, Scope.MODEL_READ)
        status = await self._jobs.get(job_id)
        if status is None:
            raise ModelNotFoundError(detail=f"no job {job_id}")
        return status

    async def run(self, model_id: str, job_id: str) -> None:
        """The detached half. Never raises to its caller.

        A background task that raises has nowhere to report, so every outcome
        is written to the job and to the model state instead. The `finally` is
        what stops a crashed pull leaving a model stuck in `downloading`
        forever, which no later operation would be willing to touch.

        **No database session is held across the pull.** The read and the two
        possible state writes each open their own short transaction, and
        progress goes to the cache in between, so this does not pin a
        connection idle-in-transaction for hours or hold VACUUM back.
        """
        model = await self._state.get(model_id)
        if model is None:
            await self._fail(job_id, model_id, "The model was removed while queued.")
            return

        runtime = self._runtimes.get(model.runtime)
        if runtime is None:
            await self._fail(job_id, model_id, "No adapter for this runtime.")
            await self._state.commit(model.id, ModelState.ERROR)
            return

        succeeded = False
        try:
            await self._pull(runtime, model, job_id)
            succeeded = True
        except Exception as exc:
            logger.exception("download_failed model=%s job=%s", model.id, job_id)
            # The message is the operator's, not the caller's: the job is only
            # readable by someone holding `model:read` on the admin API.
            await self._fail(job_id, model.id, str(exc) or "The download failed.")
        finally:
            await self._state.commit(
                model.id, ModelState.DOWNLOADED if succeeded else ModelState.ERROR
            )

        if succeeded:
            await self._jobs.set(
                JobStatus(
                    job_id=job_id,
                    state="succeeded",
                    target=model.id,
                    progress=1.0,
                    message="Downloaded",
                ),
                ttl_seconds=JOB_TTL_SECONDS,
            )

    async def _pull(self, runtime: ModelRuntimePort, model: Model, job_id: str) -> None:
        # `aclosing` for the same reason as the inference path: without it the
        # adapter's HTTP stream may outlive this function if anything below
        # raises, and the pull keeps running against a job nobody is reading.
        async with aclosing(runtime.pull(model.ref)) as progress:
            async for update in progress:
                await self._jobs.set(
                    JobStatus(
                        job_id=job_id,
                        state="running",
                        target=model.id,
                        progress=update.fraction,
                        completed_bytes=update.completed_bytes,
                        total_bytes=update.total_bytes,
                        message=update.status,
                    ),
                    ttl_seconds=JOB_TTL_SECONDS,
                )

    async def _fail(self, job_id: str, model_id: str, message: str) -> None:
        await self._jobs.set(
            JobStatus(job_id=job_id, state="failed", target=model_id, message=message),
            ttl_seconds=JOB_TTL_SECONDS,
        )

    async def _require(self, model_id: str) -> Model:
        model = await self._models.get(model_id)
        if model is None:
            raise ModelNotFoundError(detail=f"no model {model_id}")
        return model
