from __future__ import annotations

import pytest

from app.domain.entities.model import ModelState, ResourceProfile
from app.domain.exceptions import (
    InsufficientMemoryError,
    ModelStateConflictError,
)
from tests.unit.fakes import (
    FakeRuntime,
)
from tests.unit.manage_models_fixtures import (
    ADMIN,
    PROFILE,
    Harness,
    make_model,
)

pytest_plugins = ("tests.unit.manage_models_fixtures",)


async def test_loading_a_model_that_does_not_fit_is_refused() -> None:
    """A refusal, not a warning: on unified memory an over-commit does not
    fail cleanly, it drives the machine into swap."""
    resident = make_model(id="m0", alias="big", state=ModelState.LOADED)
    harness = Harness(
        [
            resident,
            make_model(
                id="m1", resource_profile=ResourceProfile(memory_gb=95.0, context_length=8192)
            ),
        ]
    )

    with pytest.raises(InsufficientMemoryError):
        await harness.use_case.load(ADMIN, "m1")

    assert harness.models.rows["m1"].state is ModelState.DOWNLOADED


async def test_an_undownloaded_model_cannot_be_loaded() -> None:
    harness = Harness([make_model(state=ModelState.NOT_DOWNLOADED)])

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.load(ADMIN, "m1")


async def test_loading_twice_is_not_an_error() -> None:
    """The caller wanted it loaded and it is. Raising would make a retry after
    a lost response look like a fault."""
    harness = Harness([make_model(state=ModelState.LOADED)])

    assert (await harness.use_case.load(ADMIN, "m1")).state is ModelState.LOADED
    assert harness.runtime.loaded == [], "nothing to do, so the runtime is not called"


async def test_a_model_the_runtime_has_evicted_can_still_be_loaded() -> None:
    """The recovery action must work in the one case it exists for.

    Deciding on `state` alone made this a no-op exactly when it mattered: a
    runtime that evicts a model out of band leaves the registry recording
    LOADED, so the early return above fired and the operator got 200 with the
    runtime never called. Seen on 2026-08-07, when Ollama evicted two models to
    fit a third — pressing Load produced no request in its log at all, and the
    only way back was to unload first.

    `RoutingService._satisfies` had already settled the rule this now follows:
    where both exist, the observation outranks the intent.
    """
    harness = Harness([make_model(state=ModelState.LOADED, observed_state=ModelState.DOWNLOADED)])

    result = await harness.use_case.load(ADMIN, "m1")

    assert harness.runtime.loaded == ["library/qwen2.5:7b"], "the runtime was never asked"
    assert result.state is ModelState.LOADED


async def test_a_model_the_runtime_holds_can_still_be_unloaded() -> None:
    """The mirror case, and the reason both were changed together.

    Ollama loads on demand, so the runtime can hold weights the registry never
    claimed. Judging by intent, `unload` refused with a 409 saying the model was
    merely downloaded — leaving the operator no way to evict something that was
    demonstrably resident and counted against nothing.
    """
    harness = Harness([make_model(state=ModelState.DOWNLOADED, observed_state=ModelState.LOADED)])

    await harness.use_case.unload(ADMIN, "m1")

    assert harness.runtime.unloaded == ["library/qwen2.5:7b"]


async def test_the_load_tells_the_runtime_which_context_to_size_for() -> None:
    """The registered profile has to reach the runtime, or it is decoration.

    `resource_profile.context_length` was stored, mapped, validated and shown
    on the models screen while nothing read it to any effect. What that cost:
    Ollama sizes its KV cache for the model's *own* declared maximum when told
    nothing, so loading `gemma4:31b-it-qat` predicted 55.8 GiB for a 262144
    token context and evicted every other resident model — on a deployment
    whose ceiling is 65536 and which had registered 32768 for that model
    (PROGRESS.md 2026-08-07).
    """
    harness = Harness([make_model()])

    await harness.use_case.load(ADMIN, "m1")

    assert harness.runtime.load_context_lengths == [PROFILE.context_length]


async def test_a_failed_load_leaves_the_model_in_error_not_loading() -> None:
    """A row stuck in `loading` is one no later operation will touch, and
    nothing sweeps it up."""
    harness = Harness([make_model()], runtime=FakeRuntime(fail_on="load"))

    with pytest.raises(RuntimeError):
        await harness.use_case.load(ADMIN, "m1")

    assert harness.models.rows["m1"].state is ModelState.ERROR
    assert ("model.loaded", "m1", "failed") in harness.audit.entries


async def test_a_load_clears_the_observation_it_has_just_invalidated() -> None:
    """The observation outranks intent in routing and in the memory budget, so
    one taken before this load would outrank the load itself: a policy asking
    for a loaded model would skip the model that was just loaded, for as long as
    the heartbeat interval, and a single-candidate policy would answer 503.
    Clearing it sends readers back to intent until the next sweep looks.
    """
    harness = Harness([make_model(observed_state=ModelState.DOWNLOADED)])

    await harness.use_case.load(ADMIN, "m1")

    row = harness.models.rows["m1"]
    assert row.state is ModelState.LOADED
    assert row.observed_state is None, "a pre-load observation must not survive the load"
    assert row.observed_memory_gb is None


async def test_an_unload_clears_the_observation_too() -> None:
    """The other direction, and the reason this belongs to `set_state` rather
    than to `load`: an observation of `loaded` taken a moment ago would keep the
    model qualifying for a `model_state: [loaded]` policy after it was evicted
    on purpose."""
    harness = Harness(
        [
            make_model(
                state=ModelState.LOADED,
                observed_state=ModelState.LOADED,
                observed_memory_gb=5.7,
            )
        ]
    )

    await harness.use_case.unload(ADMIN, "m1")

    row = harness.models.rows["m1"]
    assert row.state is ModelState.DOWNLOADED
    assert row.observed_state is None
    assert row.observed_memory_gb is None


async def test_a_failed_unload_returns_the_model_to_loaded() -> None:
    """Not to ERROR. The unload failed, so as far as anyone knows the weights
    are still resident and the memory budget must keep counting them."""
    harness = Harness([make_model(state=ModelState.LOADED)], runtime=FakeRuntime(fail_on="unload"))

    with pytest.raises(RuntimeError):
        await harness.use_case.unload(ADMIN, "m1")

    assert harness.models.rows["m1"].state is ModelState.LOADED


async def test_unloading_returns_the_model_to_downloaded() -> None:
    harness = Harness([make_model(state=ModelState.LOADED)])

    result = await harness.use_case.unload(ADMIN, "m1")

    assert result.state is ModelState.DOWNLOADED
    assert harness.runtime.unloaded == ["library/qwen2.5:7b"]


async def test_the_load_response_reports_the_observation_it_cleared() -> None:
    """The returned entity is what the caller renders, and the models table
    draws a mismatch between intent and observation in red. Answering with the
    pre-write observation shows the operator a divergence the same request just
    removed — found on the Mac Studio: an unload answered `intent=downloaded,
    observed=loaded` while the row itself held neither.
    """
    harness = Harness([make_model(observed_state=ModelState.DOWNLOADED, observed_memory_gb=4.7)])

    returned = await harness.use_case.load(ADMIN, "m1")

    assert returned.state is ModelState.LOADED
    assert returned.observed_state is None, "the response must not carry a cleared observation"
    assert returned.observed_memory_gb is None
    assert returned.observed_at is None


async def test_the_unload_response_reports_the_observation_it_cleared() -> None:
    harness = Harness(
        [
            make_model(
                state=ModelState.LOADED,
                observed_state=ModelState.LOADED,
                observed_memory_gb=5.3,
            )
        ]
    )

    returned = await harness.use_case.unload(ADMIN, "m1")

    assert returned.state is ModelState.DOWNLOADED
    assert returned.observed_state is None
    assert returned.observed_memory_gb is None
