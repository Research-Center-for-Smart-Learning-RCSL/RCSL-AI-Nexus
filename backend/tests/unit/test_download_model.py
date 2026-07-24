"""Model downloads as detached jobs.

The interesting cases are all about what the row looks like afterwards. A
download that crashes must not leave a model in `downloading`, because nothing
sweeps that up and no later operation will touch it: the model becomes
permanently unusable through the UI.
"""

from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.download_model import DownloadModel
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.model import Model, ModelState, PullProgress, ResourceProfile, RuntimeKind
from app.domain.exceptions import ModelNotFoundError, ModelStateConflictError, NotAuthorizedError
from tests.unit.fakes import FakeAudit, FakeJobs, FakeModels, FakeRuntime

ADMIN = Actor(
    id="admin-1", display="admin", role=Role.ADMIN, source="tailnet", scopes=frozenset(Scope)
)
READER = Actor(
    id="u2",
    display="user",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.MODEL_READ}),
)

UPDATES = (
    PullProgress(status="pulling manifest"),
    PullProgress(status="downloading", completed_bytes=500, total_bytes=1000),
    PullProgress(status="verifying", completed_bytes=1000, total_bytes=1000),
)


def make_model(state: ModelState = ModelState.NOT_DOWNLOADED) -> Model:
    return Model(
        id="m1",
        alias="chat-main",
        ref="library/qwen2.5:7b",
        runtime=RuntimeKind.OLLAMA,
        node_id="node-1",
        state=state,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=8.0, context_length=8192),
    )


class Harness:
    def __init__(self, state: ModelState = ModelState.NOT_DOWNLOADED, **runtime_kwargs) -> None:
        self.models = FakeModels([make_model(state)])
        self.jobs = FakeJobs()
        self.audit = FakeAudit()
        self.runtime = FakeRuntime(pull_updates=UPDATES, **runtime_kwargs)

        self.use_case = DownloadModel(
            models=self.models,
            runtimes={RuntimeKind.OLLAMA: self.runtime},
            jobs=self.jobs,
            authz=RoleAuthorization(),
            audit=self.audit,
        )


async def test_starting_claims_the_model_before_the_task_runs() -> None:
    """The state is written while the caller is still waiting, so a second
    click is refused rather than starting a second pull of the same weights."""
    harness = Harness()

    job = await harness.use_case.start(ADMIN, "m1")

    assert job.state == "queued"
    assert harness.models.rows["m1"].state is ModelState.DOWNLOADING

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.start(ADMIN, "m1")


async def test_a_loaded_model_cannot_be_redownloaded() -> None:
    harness = Harness(ModelState.LOADED)

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.start(ADMIN, "m1")


async def test_a_reader_cannot_start_a_download() -> None:
    harness = Harness()
    with pytest.raises(NotAuthorizedError):
        await harness.use_case.start(READER, "m1")


async def test_progress_is_published_and_the_model_ends_downloaded() -> None:
    harness = Harness()
    job = await harness.use_case.start(ADMIN, "m1")

    await harness.use_case.run("m1", job.job_id)

    states = [s.state for s in harness.jobs.history]
    assert states[0] == "queued"
    assert "running" in states
    assert states[-1] == "succeeded"
    assert harness.models.rows["m1"].state is ModelState.DOWNLOADED


async def test_a_stage_with_no_byte_count_reports_no_progress() -> None:
    """Ollama sends manifest and verification stages with no totals. Inventing
    a number there makes a bar sit at zero and then jump."""
    harness = Harness()
    job = await harness.use_case.start(ADMIN, "m1")

    await harness.use_case.run("m1", job.job_id)

    manifest = next(s for s in harness.jobs.history if s.message == "pulling manifest")
    assert manifest.progress is None

    downloading = next(s for s in harness.jobs.history if s.message == "downloading")
    assert downloading.progress == pytest.approx(0.5)


async def test_a_failed_pull_leaves_error_not_downloading() -> None:
    """`downloading` is a state nothing sweeps up and no later operation will
    touch, so the model would be permanently unusable through the UI."""
    harness = Harness(fail_on="pull")
    job = await harness.use_case.start(ADMIN, "m1")

    await harness.use_case.run("m1", job.job_id)

    assert harness.models.rows["m1"].state is ModelState.ERROR
    assert harness.jobs.rows[job.job_id].state == "failed"


async def test_the_pull_stream_is_closed_even_when_it_fails() -> None:
    """Without `aclosing` the adapter's HTTP stream can outlive the function
    and keep pulling for a job nobody is reading."""
    harness = Harness(fail_on="pull")
    job = await harness.use_case.start(ADMIN, "m1")

    await harness.use_case.run("m1", job.job_id)

    assert harness.runtime.pull_closed


async def test_the_background_half_never_raises() -> None:
    """It has nowhere to report to. Every outcome goes to the job and the
    model state instead."""
    harness = Harness()

    await harness.use_case.run("does-not-exist", "job-1")

    assert harness.jobs.rows["job-1"].state == "failed"


async def test_an_unknown_job_is_a_not_found() -> None:
    harness = Harness()
    with pytest.raises(ModelNotFoundError):
        await harness.use_case.status(ADMIN, "no-such-job")
