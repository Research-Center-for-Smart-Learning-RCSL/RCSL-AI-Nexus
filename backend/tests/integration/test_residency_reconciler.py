"""Residency intent and the reconciler against real PostgreSQL (#49).

The runtime is simulated in process; nothing here reaches Ollama or an agent.
What is real is everything the reconciler trusts: the migration's empty intent,
the targeted intent write, the observation stamps, the `node_operations`
block, the advisory lock that keeps two reconcilers apart, and the
`ManageModels` load path with its budget and audit rows.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.node_serialisation import PostgresNodeSerialisation
from app.adapters.persistence.repositories import PostgresModelRepository, PostgresNodeRepository
from app.application.audit_subject import RESIDENCY_RECONCILER_ID
from app.application.use_cases.reconcile_residency import PassResult, ReconcileResidency
from app.domain.entities.model import (
    Model,
    ModelState,
    ResourceProfile,
    RuntimeKind,
    RuntimeResidency,
)
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import ModelStateConflictError
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import dispose_engine, get_engine, init_engine, session_scope
from app.infrastructure.di.inference_runtime import manage_models_for
from app.infrastructure.di.shared import build_audit
from app.infrastructure.residency_reconciler import (
    HeartbeatObserver,
    ManageModelsRestorer,
    PostgresReconcilerState,
)
from tests.integration.conftest import _alembic_config
from tests.unit.fakes import FakeRuntime
from tests.unit.manage_models_fixtures import ADMIN

PREVIOUS_HEAD = "f2c7d9e40b31"


def test_migration_starts_every_row_without_intent_and_downgrades(database_url):
    config = _alembic_config(database_url)
    command.downgrade(config, PREVIOUS_HEAD)

    async def seed() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO nodes (id, name, address, status, total_memory_gb, runtimes) "
                        "VALUES ('n1', 'n1', '100.64.0.1', 'online', 64, '[\"ollama\"]')"
                    )
                )
                for alias, state in [("kept", "loaded"), ("idle", "downloaded"), ("bad", "error")]:
                    await connection.execute(
                        text(
                            "INSERT INTO models (id, alias, ref, runtime, node_id, state, "
                            "capabilities, memory_gb, context_length) VALUES "
                            "(:id, :alias, :ref, 'ollama', 'n1', :state, '[]', 1, 2048)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "alias": alias,
                            "ref": f"{alias}:t",
                            "state": state,
                        },
                    )
        finally:
            await engine.dispose()

    async def intents() -> dict[str, tuple[bool, int]]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(
                    text("SELECT alias, desired_resident, desired_version FROM models")
                )
                return {r[0]: (r[1], r[2]) for r in rows}
        finally:
            await engine.dispose()

    async def columns() -> set[str]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'models'"
                    )
                )
                return {r[0] for r in rows}
        finally:
            await engine.dispose()

    asyncio.run(seed())
    command.upgrade(config, "head")
    # Not even `loaded`: a row can say so for weights unloaded outside the
    # registry, and the reconciler would reload them unasked.
    assert asyncio.run(intents()) == {
        "kept": (False, 0),
        "idle": (False, 0),
        "bad": (False, 0),
    }
    command.downgrade(config, PREVIOUS_HEAD)
    assert not {"desired_resident", "desired_version"} & asyncio.run(columns())
    command.upgrade(config, "head")


def _node(node_id: str = "local") -> Node:
    return Node(
        id=node_id,
        name=f"name-{node_id}",
        address="100.64.0.1",
        status=NodeStatus.ONLINE,
        total_memory_gb=64.0,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
    )


def _model(alias: str, memory_gb: float, *, node_id: str = "local", **overrides: object) -> Model:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "alias": alias,
        "ref": f"{alias}:tag",
        "runtime": RuntimeKind.OLLAMA,
        "node_id": node_id,
        "state": ModelState.LOADED,
        "capabilities": frozenset({"chat"}),
        "resource_profile": ResourceProfile(memory_gb=memory_gb, context_length=4096),
    }
    defaults.update(overrides)
    return Model(**defaults)  # type: ignore[arg-type]


async def test_intent_is_versioned_and_a_registry_save_does_not_revert_it(database_url):
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    model = _model("kept", 6)
    try:
        async with sessions() as session:
            await PostgresNodeRepository(session).save(_node())
            await PostgresModelRepository(session).save(model)
            await session.commit()
        async with sessions() as session:
            stale = await PostgresModelRepository(session).get(model.id)
        async with sessions() as session:
            repo = PostgresModelRepository(session)
            assert await repo.set_desired_residency(model.id, True) == 1
            assert await repo.set_desired_residency(model.id, False) == 2
            assert await repo.set_desired_residency("missing", True) is None
            await session.commit()
        async with sessions() as session:
            # A provisioning merge or an edit made from an older read.
            await PostgresModelRepository(session).save(replace(stale, alias="edited"))
            await session.commit()
        async with sessions() as session:
            stored = await PostgresModelRepository(session).get(model.id)
            assert stored.alias == "edited"
            assert (stored.desired_resident, stored.desired_version) == (False, 2)
    finally:
        await engine.dispose()


@pytest.fixture
async def global_engine(database_url):
    """The reconciler's adapters use the process-wide engine, as in the admin."""
    await dispose_engine()
    get_settings.cache_clear()
    init_engine(get_settings())
    yield
    await dispose_engine()


async def test_unknown_operation_blocks_the_node(global_engine):
    async with session_scope() as session:
        await PostgresNodeRepository(session).save(_node())
    state = PostgresReconcilerState()
    assert not await state.node_blocked("local")
    async with session_scope() as session:
        await session.execute(
            text(
                "INSERT INTO node_operations (node_id, op_id, kind, state, origin_generation, "
                "origin_boot_id, owner_generation, submitted_at) VALUES "
                "('local', 'op', 'load', 'outcome_unknown', 1, 'boot', 1, now())"
            )
        )
    assert await state.node_blocked("local")


async def test_a_second_reconciler_is_kept_off_the_node(global_engine):
    serialisation = PostgresNodeSerialisation(get_engine)
    async with serialisation.hold("local") as first:
        assert first
        async with PostgresNodeSerialisation(get_engine).hold("local") as second:
            assert not second
        async with serialisation.hold("other") as unrelated:
            assert unrelated
    async with PostgresNodeSerialisation(get_engine).hold("local") as again:
        assert again


class SimulatedOllama(FakeRuntime):
    """Holds what it was told to load, and says so when asked."""

    def __init__(self, on_disk: set[str]) -> None:
        super().__init__()
        self.on_disk = on_disk
        self.resident: dict[str, float] = {}

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        await super().load(ref, context_length=context_length)
        self.resident[ref] = 1.0

    async def unload(self, ref: str) -> None:
        await super().unload(ref)
        self.resident.pop(ref, None)

    async def residency(self) -> RuntimeResidency | None:
        return RuntimeResidency(resident=dict(self.resident), on_disk=frozenset(self.on_disk))


def _admin(runtime: FakeRuntime) -> tuple[SimpleNamespace, Settings]:
    app = SimpleNamespace(
        state=SimpleNamespace(
            runtimes={RuntimeKind.OLLAMA: runtime},
            authz=RoleAuthorization(),
            audit=build_audit(),
            token_counter=None,
        )
    )
    settings = get_settings().model_copy(
        update={"residency_reconciler_enabled": True, "host_metrics_url": ""}
    )
    return app, settings


async def _stored(model_id: str) -> Model:
    async with session_scope() as session:
        stored = await PostgresModelRepository(session).get(model_id)
    assert stored is not None
    return stored


async def test_operator_load_and_unload_complete_against_real_postgres(global_engine):
    """The request transaction must not hold the row while an independent
    transaction writes the same row: that waited for ever, because the request
    was itself waiting for the independent write. A timeout, not a hang."""
    model = _model("qwen", 6, state=ModelState.DOWNLOADED)
    async with session_scope() as session:
        await PostgresNodeRepository(session).save(_node())
        await PostgresModelRepository(session).save(model)
    runtime = SimulatedOllama({model.ref})
    app, settings = _admin(runtime)

    async def operator(action: str) -> Model:
        async with session_scope() as session:
            use_case = manage_models_for(app, session, settings)  # type: ignore[arg-type]
            return await getattr(use_case, action)(ADMIN, model.id)

    loaded = await asyncio.wait_for(operator("load"), 10)
    assert loaded.state is ModelState.LOADED
    stored = await _stored(model.id)
    assert stored.state is ModelState.LOADED
    assert (stored.desired_resident, stored.desired_version) == (True, 1)

    unloaded = await asyncio.wait_for(operator("unload"), 10)
    assert unloaded.state is ModelState.DOWNLOADED
    stored = await _stored(model.id)
    assert stored.state is ModelState.DOWNLOADED
    assert (stored.desired_resident, stored.desired_version) == (False, 2)
    assert runtime.loaded == [model.ref] and runtime.unloaded == [model.ref]


async def test_a_failed_operator_load_keeps_its_intent_against_real_postgres(global_engine):
    model = _model("qwen", 6, state=ModelState.DOWNLOADED)
    async with session_scope() as session:
        await PostgresNodeRepository(session).save(_node())
        await PostgresModelRepository(session).save(model)
    app, settings = _admin(FakeRuntime(fail_on="load"))

    async def load() -> Model:
        async with session_scope() as session:
            use_case = manage_models_for(app, session, settings)  # type: ignore[arg-type]
            return await use_case.load(ADMIN, model.id)

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(load(), 10)
    stored = await _stored(model.id)
    # ERROR and the intent both survive the request's rollback.
    assert stored.state is ModelState.ERROR
    assert (stored.desired_resident, stored.desired_version) == (True, 1)


class HeldOllama(SimulatedOllama):
    """A load that does not return until the test lets it."""

    def __init__(self, on_disk: set[str]) -> None:
        super().__init__(on_disk)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def load(self, ref: str, *, context_length: int | None = None) -> None:
        self.started.set()
        await self.release.wait()
        await super().load(ref, context_length=context_length)


async def test_two_loads_on_one_node_never_pass_the_budget_together(global_engine):
    """Each read the occupying set before the other committed LOADING; the
    node lock now refuses the second instead of letting both over-commit."""
    first, second = (
        _model("first", 6, state=ModelState.DOWNLOADED),
        _model("second", 6, state=ModelState.DOWNLOADED),
    )
    async with session_scope() as session:
        await PostgresNodeRepository(session).save(_node())
        for model in (first, second):
            await PostgresModelRepository(session).save(model)
    runtime = HeldOllama({first.ref, second.ref})
    app, settings = _admin(runtime)

    async def load(model_id: str) -> Model:
        async with session_scope() as session:
            use_case = manage_models_for(app, session, settings)  # type: ignore[arg-type]
            return await use_case.load(ADMIN, model_id)

    in_flight = asyncio.create_task(load(first.id))
    await asyncio.wait_for(runtime.started.wait(), 10)
    with pytest.raises(ModelStateConflictError):
        await asyncio.wait_for(load(second.id), 10)
    # The reconciler is kept off the node the same way.
    async with PostgresNodeSerialisation(get_engine).hold("local") as held:
        assert not held
    runtime.release.set()
    assert (await asyncio.wait_for(in_flight, 10)).state is ModelState.LOADED
    assert (await _stored(second.id)).desired_version == 0, "a refusal records no intent"

    # Released with the load: the next one goes through.
    assert (await asyncio.wait_for(load(second.id), 10)).state is ModelState.LOADED


async def test_an_operator_load_is_refused_while_the_reconciler_holds_the_node(global_engine):
    model = _model("qwen", 6, state=ModelState.DOWNLOADED)
    async with session_scope() as session:
        await PostgresNodeRepository(session).save(_node())
        await PostgresModelRepository(session).save(model)
    runtime = SimulatedOllama({model.ref})
    app, settings = _admin(runtime)

    async with PostgresNodeSerialisation(get_engine).hold("local") as held:
        assert held
        async with session_scope() as session:
            use_case = manage_models_for(app, session, settings)  # type: ignore[arg-type]
            with pytest.raises(ModelStateConflictError):
                await asyncio.wait_for(use_case.load(ADMIN, model.id), 10)
    assert runtime.loaded == []


async def test_restart_restores_the_desired_set_largest_first(global_engine):
    gemma, qwen, embedder, unwanted = (
        _model("gemma", 44),
        _model("qwen", 6),
        _model("embedder", 1),
        _model("unwanted", 2),
    )
    async with session_scope() as session:
        await PostgresNodeRepository(session).save(_node())
        repo = PostgresModelRepository(session)
        for model in (gemma, qwen, embedder, unwanted):
            await repo.save(model)
        for model in (gemma, qwen, embedder):
            await repo.set_desired_residency(model.id, True)

    # After the restart: everything on disk, nothing held.
    runtime = SimulatedOllama({m.ref for m in (gemma, qwen, embedder, unwanted)})
    app, settings = _admin(runtime)
    observer = HeartbeatObserver(app)  # type: ignore[arg-type]
    reconciler = ReconcileResidency(
        PostgresReconcilerState(),
        observer,
        ManageModelsRestorer(app, settings),  # type: ignore[arg-type]
        PostgresNodeSerialisation(get_engine),
        enabled=True,
    )
    node = _node()

    await observer.observe(node)
    assert [o.result for o in await reconciler.run_once()] == [PassResult.IDLE]
    assert runtime.loaded == []
    await asyncio.sleep(0.01)
    await observer.observe(node)
    (outcome,) = await reconciler.run_once()

    assert outcome.result is PassResult.RESTORED
    assert runtime.loaded == ["gemma:tag", "qwen:tag", "embedder:tag"]
    # The registered context, nothing else chosen here.
    assert runtime.load_context_lengths == [4096, 4096, 4096]
    async with session_scope() as session:
        rows = {m.alias: m for m in await PostgresModelRepository(session).list_all()}
        audited = await session.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE actor_id = :actor AND action = 'model.loaded'"
            ),
            {"actor": RESIDENCY_RECONCILER_ID},
        )
        assert audited.scalar_one() == 3
    for alias in ("gemma", "qwen", "embedder"):
        assert rows[alias].observed_state is ModelState.LOADED
        assert rows[alias].desired_resident and rows[alias].desired_version == 1
    assert rows["unwanted"].observed_state is ModelState.DOWNLOADED
