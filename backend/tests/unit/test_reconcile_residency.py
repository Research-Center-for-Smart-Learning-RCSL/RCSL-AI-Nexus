"""The residency reconciler's pass, against a simulated node (#49 §2, §3).

The simulation keeps the properties the rules depend on: a load clears the
model's observation, as `set_state` does; only an observation writes a fresh
stamp; and a load can evict siblings, as gemma4-31b-q8 does on the production
host when it is not loaded first. Nothing here reaches a runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.application.use_cases.reconcile_residency import PassResult, ReconcileResidency
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import InsufficientMemoryError
from app.domain.services.residency_reconciliation import GIVE_UP_AFTER_WASTED_PASSES
from tests.unit.manage_models_fixtures import NODE, make_model

START = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _desired(model_id: str, alias: str, memory_gb: float, **overrides: object) -> Model:
    defaults: dict[str, object] = {
        "id": model_id,
        "alias": alias,
        "ref": f"{alias}:tag",
        "state": ModelState.LOADED,
        "resource_profile": ResourceProfile(memory_gb, 8192),
        "desired_resident": True,
        "desired_version": 1,
    }
    defaults.update(overrides)
    return make_model(**defaults)


class World:
    """One node, its registry rows and what its runtime holds."""

    def __init__(self, models: list[Model], node: Node = NODE) -> None:
        self.node = node
        self.rows = {m.id: m for m in models}
        self.resident: set[str] = set()
        self.now = START
        self.blocked = False
        self.evicts: dict[str, set[str]] = {}
        self.fail_loads: set[str] = set()
        self.loads: list[str] = []
        self.releases: list[str] = []
        self.observations = 0
        self.on_restore: dict[str, object] = {}
        self.held_elsewhere = False

    # -- ReconcilerStatePort --------------------------------------------
    async def nodes(self) -> list[Node]:
        return [self.node]

    async def models_on(self, node_id: str) -> list[Model]:
        return [m for m in self.rows.values() if m.node_id == node_id]

    async def node_blocked(self, node_id: str) -> bool:
        return self.blocked

    async def time(self) -> datetime:
        return self.now

    # -- the heartbeat ---------------------------------------------------
    async def observe(self, node: Node) -> None:
        self.observations += 1
        for model in list(self.rows.values()):
            state = ModelState.LOADED if model.id in self.resident else ModelState.DOWNLOADED
            self.rows[model.id] = replace(model, observed_state=state, observed_at=self.now)

    async def heartbeat(self, seconds: float = 30) -> None:
        self.now += timedelta(seconds=seconds)
        await self.observe(self.node)

    def lose_observation(self) -> None:
        for model in list(self.rows.values()):
            self.rows[model.id] = replace(model, observed_state=None, observed_at=None)

    # -- ModelRestorerPort -------------------------------------------------
    async def restore(self, model_id: str) -> Model:
        self.loads.append(self.rows[model_id].alias)
        hook = self.on_restore.get(model_id)
        if callable(hook):
            hook()
        if model_id in self.fail_loads:
            self.rows[model_id] = replace(
                self.rows[model_id], state=ModelState.ERROR, observed_state=None, observed_at=None
            )
            raise InsufficientMemoryError(required_gb=1.0, available_gb=0.0)
        self.resident -= self.evicts.get(model_id, set())
        self.resident.add(model_id)
        self.rows[model_id] = replace(
            self.rows[model_id], state=ModelState.LOADED, observed_state=None, observed_at=None
        )
        return self.rows[model_id]

    async def release(self, model_id: str) -> Model:
        self.releases.append(self.rows[model_id].alias)
        self.resident.discard(model_id)
        self.rows[model_id] = replace(
            self.rows[model_id], state=ModelState.DOWNLOADED, observed_state=None, observed_at=None
        )
        return self.rows[model_id]

    # -- NodeSerialisationPort ---------------------------------------------
    @asynccontextmanager
    async def hold(self, node_id: str) -> AsyncIterator[bool]:
        yield not self.held_elsewhere


class _State:
    def __init__(self, world: World) -> None:
        self._w = world

    async def nodes(self) -> list[Node]:
        return await self._w.nodes()

    async def models_on(self, node_id: str) -> list[Model]:
        return await self._w.models_on(node_id)

    async def node_blocked(self, node_id: str) -> bool:
        return await self._w.node_blocked(node_id)

    async def now(self) -> datetime:
        return await self._w.time()


def _reconciler(world: World, *, enabled: bool = True, suspended: bool = False):
    async def is_suspended() -> bool:
        return suspended

    return ReconcileResidency(
        _State(world), world, world, world, enabled=enabled, suspended=is_suspended
    )


def _restart_world() -> World:
    """The production set after a runtime restart: intent loaded, nothing held."""
    return World(
        [
            _desired("e", "embedder", 1),
            _desired("q", "qwen", 6),
            _desired("g", "gemma", 44),
        ]
    )


async def _settle(world: World, reconciler: ReconcileResidency, beats: int = 2):
    outcomes = []
    for _ in range(beats):
        await world.heartbeat()
        outcomes = await reconciler.run_once()
    return outcomes


async def test_disabled_never_reads_or_loads():
    world = _restart_world()
    reconciler = _reconciler(world, enabled=False)
    for _ in range(4):
        await world.heartbeat()
        assert await reconciler.run_once() == []
    assert world.loads == []


async def test_one_absent_observation_is_not_enough():
    world = _restart_world()
    reconciler = _reconciler(world)
    await world.heartbeat()
    (outcome,) = await reconciler.run_once()
    assert outcome.result is PassResult.IDLE
    # Looking again at the same answer is still one observation.
    assert (await reconciler.run_once())[0].result is PassResult.IDLE
    assert world.loads == []


async def test_restores_the_whole_set_largest_first_after_two_observations():
    world = _restart_world()
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.RESTORED
    assert world.loads == ["gemma", "qwen", "embedder"]
    assert outcome.restored == ("gemma", "qwen", "embedder")
    # Re-observed after each load: the whole node, three times.
    assert world.observations == 2 + 3
    assert world.resident == {"g", "q", "e"}


async def test_a_lost_observation_between_answers_restarts_the_count():
    world = _restart_world()
    reconciler = _reconciler(world)
    await world.heartbeat()
    await reconciler.run_once()
    world.now += timedelta(seconds=30)
    world.lose_observation()
    await reconciler.run_once()
    await world.heartbeat()
    assert (await reconciler.run_once())[0].result is PassResult.IDLE
    assert world.loads == []


async def test_unknown_residency_is_never_evidence():
    world = _restart_world()
    reconciler = _reconciler(world)
    for _ in range(4):
        world.now += timedelta(seconds=30)
        world.lose_observation()
        assert (await reconciler.run_once())[0].result is PassResult.IDLE
    assert world.loads == []


async def test_an_evicted_sibling_is_requeued_in_a_repair_round():
    world = _restart_world()
    # Loaded out of order, the small ones would be evicted by gemma; here the
    # embedder's load evicts qwen, which the pass must notice and repair.
    world.evicts["e"] = {"q"}
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.RESTORED
    assert world.loads == ["gemma", "qwen", "embedder", "qwen"]
    assert world.resident == {"g", "q", "e"}


async def test_repair_rounds_are_bounded_then_the_node_backs_off():
    world = _restart_world()
    # Each small model evicts the other: never settles.
    world.evicts = {"q": {"e"}, "e": {"q"}}
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.FAILED
    assert outcome.reason == "repair_rounds_exhausted"
    # One first round, then two repair rounds of whichever model was evicted.
    assert world.loads == ["gemma", "qwen", "embedder", "qwen", "embedder"]

    loads = len(world.loads)
    world.now += timedelta(seconds=20)
    await world.observe(world.node)
    assert (await reconciler.run_once())[0].result is PassResult.BACKING_OFF
    assert len(world.loads) == loads


async def test_backoff_doubles_after_each_failed_pass():
    world = _restart_world()
    world.fail_loads = {"g"}
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.FAILED
    assert outcome.reason == "load_failed:InsufficientMemoryError"
    assert world.loads == ["gemma"]

    # 30 s later the backoff has expired, but evidence must be gathered again.
    await world.heartbeat(31)
    assert (await reconciler.run_once())[0].result is PassResult.IDLE
    await world.heartbeat(30)
    assert (await reconciler.run_once())[0].result is PassResult.FAILED
    assert world.loads == ["gemma", "gemma"]

    # The second failure waits 60 s: still backing off at 45.
    await world.heartbeat(45)
    assert (await reconciler.run_once())[0].result is PassResult.BACKING_OFF


async def test_retry_after_error_once_evidence_returns():
    world = _restart_world()
    world.fail_loads = {"g"}
    reconciler = _reconciler(world)
    await _settle(world, reconciler)
    assert world.rows["g"].state is ModelState.ERROR
    world.fail_loads = set()
    await world.heartbeat(31)
    await reconciler.run_once()
    (outcome,) = await _settle(world, reconciler, beats=1)
    assert outcome.result is PassResult.RESTORED
    assert world.resident == {"g", "q", "e"}


async def test_never_dispatches_while_the_node_is_blocked():
    world = _restart_world()
    world.blocked = True
    reconciler = _reconciler(world)
    await world.heartbeat()
    await reconciler.run_once()
    for _ in range(4):
        await world.heartbeat()
        assert (await reconciler.run_once())[0].result is PassResult.BLOCKED
    assert world.loads == []


async def test_a_block_that_appears_mid_pass_stops_it():
    world = _restart_world()

    def block() -> None:
        world.blocked = True

    world.on_restore["g"] = block
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.BLOCKED
    assert world.loads == ["gemma"]


async def test_waits_for_a_lifecycle_operation_already_in_flight():
    world = _restart_world()
    world.rows["q"] = replace(world.rows["q"], state=ModelState.LOADING)
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.BUSY
    assert world.loads == []


async def test_another_holder_of_the_node_means_skip():
    world = _restart_world()
    world.held_elsewhere = True
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.BUSY
    assert outcome.reason == "held_elsewhere"
    assert world.loads == []


async def test_suspended_does_nothing():
    world = _restart_world()
    reconciler = _reconciler(world, suspended=True)
    (outcome,) = await _settle(world, reconciler, beats=3)
    assert outcome.result is PassResult.SUSPENDED
    assert world.loads == []


async def test_only_desired_ollama_models_are_restored():
    world = _restart_world()
    world.rows["q"] = replace(world.rows["q"], desired_resident=False)
    world.rows["m"] = _desired("m", "mlx-model", 90, runtime=RuntimeKind.MLX)
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.RESTORED
    assert world.loads == ["gemma", "embedder"]


async def test_cancellation_before_the_load_is_honoured():
    world = _restart_world()

    def withdraw_qwen() -> None:
        world.rows["q"] = replace(world.rows["q"], desired_resident=False, desired_version=2)

    world.on_restore["g"] = withdraw_qwen
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.RESTORED
    assert world.loads == ["gemma", "embedder"]
    assert world.releases == []


async def test_cancellation_during_the_load_unloads_the_fresh_weights():
    world = _restart_world()

    def withdraw_gemma() -> None:
        world.rows["g"] = replace(world.rows["g"], desired_resident=False, desired_version=2)

    world.on_restore["g"] = withdraw_gemma
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.RESTORED
    assert world.loads == ["gemma", "qwen", "embedder"]
    assert world.releases == ["gemma"]
    assert outcome.released == ("gemma",)
    assert "g" not in world.resident
    # The flag the operator withdrew stays withdrawn.
    assert world.rows["g"].desired_resident is False


async def test_an_unhealthy_node_is_left_alone():
    world = _restart_world()
    world.node = replace(NODE, status=NodeStatus.OFFLINE)
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler)
    assert outcome.result is PassResult.UNHEALTHY
    assert world.loads == []


async def test_nothing_to_do_when_everything_desired_is_resident():
    world = _restart_world()
    world.resident = {"g", "q", "e"}
    reconciler = _reconciler(world)
    (outcome,) = await _settle(world, reconciler, beats=3)
    assert outcome.result is PassResult.IDLE
    assert world.loads == []


async def _until(world: World, reconciler: ReconcileResidency, stop: PassResult, beats: int = 400):
    """Heartbeats every 30 s until `stop`, returning every result that acted."""
    seen = []
    for _ in range(beats):
        await world.heartbeat()
        (outcome,) = await reconciler.run_once()
        if outcome.result not in (PassResult.IDLE, PassResult.BACKING_OFF):
            seen.append(outcome.result)
        if outcome.result is stop:
            break
    return seen


async def test_a_set_that_cannot_co_reside_is_given_up_on():
    """Two repair rounds and a 15 min backoff would still reload it for ever."""
    world = _restart_world()
    world.evicts = {"q": {"e"}, "e": {"q"}}
    reconciler = _reconciler(world)

    seen = await _until(world, reconciler, PassResult.GAVE_UP)
    assert seen == [PassResult.FAILED] * GIVE_UP_AFTER_WASTED_PASSES + [PassResult.GAVE_UP]
    loads = len(world.loads)
    await _until(world, reconciler, PassResult.RESTORED, beats=100)
    assert len(world.loads) == loads, "nothing is reloaded once it has given up"

    # An operator's change of intent is a new request: it tries again.
    world.rows["e"] = replace(world.rows["e"], desired_version=2)
    world.evicts = {}
    assert await _until(world, reconciler, PassResult.RESTORED) == [PassResult.RESTORED]
    assert world.resident == {"g", "q", "e"}


async def test_failures_that_load_nothing_never_give_up():
    """A refusal or an outage costs no reload; backing off is enough."""
    world = _restart_world()
    world.fail_loads = {"g"}
    reconciler = _reconciler(world)
    seen = await _until(world, reconciler, PassResult.GAVE_UP)
    assert PassResult.GAVE_UP not in seen
    assert len(seen) > GIVE_UP_AFTER_WASTED_PASSES
