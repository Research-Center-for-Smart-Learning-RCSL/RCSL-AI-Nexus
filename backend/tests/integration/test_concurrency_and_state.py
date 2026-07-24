"""The persistence fixes that only a real database can demonstrate.

Every case here passed against the in-memory fakes while being wrong in
Postgres, or is about a transaction boundary a fake has no notion of: a failed
load whose ERROR write must survive the request rollback, a targeted update
that must not revert a concurrent revoke, a transient state a deploy must
reconcile.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.adapters.persistence.model_state import ModelStateCommitter
from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresUserRepository,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.user import User
from app.infrastructure.provision import TRANSIENT_RECONCILIATION
from tests.integration.conftest import make_session_factory

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


async def _node(sessions) -> Node:
    node = Node(
        id="n1",
        name="studio",
        address="100.64.0.1",
        status=NodeStatus.ONLINE,
        total_memory_gb=64.0,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
    )
    async with sessions() as s:
        await PostgresNodeRepository(s).save(node)
        await s.commit()
    return node


def _model(state: ModelState, memory: float = 8.0) -> Model:
    handle = uuid.uuid4().hex[:6]
    return Model(
        id=str(uuid.uuid4()),
        alias=f"m-{handle}",
        # Distinct per model: there is a unique constraint on
        # (node_id, runtime, ref), so a shared ref collides.
        ref=f"library/x-{handle}:1",
        runtime=RuntimeKind.OLLAMA,
        node_id="n1",
        state=state,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=memory, context_length=1024),
    )


async def test_the_state_committer_survives_a_rollback(database_url: str) -> None:
    """The load failure path writes ERROR through this and then raises; the
    raise rolls the request transaction back, so the ERROR has to be in a
    transaction of its own or it goes with it.

    The request-shaped transaction here does an unrelated write (registering a
    second model) rather than touching the model under test, because in
    production `load` no longer writes the failing model through the request
    session at all — the whole point of the committer. Writing it here too
    would just make the committer's UPDATE block on the request's own row lock.
    """
    sessions = make_session_factory(database_url)
    await _node(sessions)
    model = _model(ModelState.DOWNLOADED)
    async with sessions() as s:
        await PostgresModelRepository(s).save(model)
        await s.commit()

    committer = ModelStateCommitter(sessions)

    try:
        async with sessions() as request:
            # Unrelated request work that will be rolled back.
            await PostgresModelRepository(request).save(_model(ModelState.NOT_DOWNLOADED))
            await committer.commit(model.id, ModelState.ERROR)
            raise RuntimeError("the runtime call failed")
    except RuntimeError:
        pass

    async with sessions() as s:
        repo = PostgresModelRepository(s)
        stored = await repo.get(model.id)
        all_models = await repo.list_all()

    assert stored is not None
    # The independent ERROR survived; the request's second model did not.
    assert stored.state is ModelState.ERROR
    assert len(all_models) == 1


async def test_list_occupying_memory_counts_loading(database_url: str) -> None:
    """A LOADING model already holds or is about to hold its memory, so the
    budget must count it or two concurrent loads each see room the other is
    taking."""
    sessions = make_session_factory(database_url)
    await _node(sessions)
    async with sessions() as s:
        repo = PostgresModelRepository(s)
        await repo.save(_model(ModelState.LOADED))
        await repo.save(_model(ModelState.LOADING))
        await repo.save(_model(ModelState.DOWNLOADED))
        await s.commit()

    async with sessions() as s:
        occupying = await PostgresModelRepository(s).list_occupying_memory("n1")

    assert {m.state for m in occupying} == {ModelState.LOADED, ModelState.LOADING}


async def test_reconciliation_clears_stranded_transient_states(database_url: str) -> None:
    """A crash leaves a model mid-operation; the next deploy runs this so the
    row is not a permanent dead end reachable only by hand-edited SQL."""
    sessions = make_session_factory(database_url)
    await _node(sessions)
    async with sessions() as s:
        repo = PostgresModelRepository(s)
        downloading = _model(ModelState.DOWNLOADING)
        loading = _model(ModelState.LOADING)
        unloading = _model(ModelState.UNLOADING)
        for model in (downloading, loading, unloading):
            await repo.save(model)
        await s.commit()

    async with sessions() as s:
        moved = await PostgresModelRepository(s).reconcile_transient_states(
            TRANSIENT_RECONCILIATION
        )
        await s.commit()

    async with sessions() as s:
        repo = PostgresModelRepository(s)
        states = {m.alias: m.state for m in await repo.list_all()}

    assert moved == 3
    assert states[downloading.alias] is ModelState.ERROR
    assert states[loading.alias] is ModelState.ERROR
    # An interrupted unload leaves the weights resident, so it goes to LOADED.
    assert states[unloading.alias] is ModelState.LOADED


async def test_a_targeted_key_update_does_not_revert_a_concurrent_revoke(
    database_url: str,
) -> None:
    """The merge-race: a full-row save of a read-then-edited key wrote
    `revoked_at` back from what it read, reviving a key a concurrent revoke had
    killed. The targeted update touches named columns only and refuses when
    the key is already revoked."""
    sessions = make_session_factory(database_url)
    user = User(id=str(uuid.uuid4()), login="o@example.org", display_name="O", role=Role.ADMIN)
    async with sessions() as s:
        await PostgresUserRepository(s).save(user)
        await s.commit()

    key = ApiKey(
        id=str(uuid.uuid4()),
        key_id="0123456789abcdef",
        digest="d",
        name="ci",
        owner_id=user.id,
        expires_at=NOW + timedelta(days=30),
    )
    async with sessions() as s:
        await PostgresApiKeyRepository(s).save(key)
        await s.commit()

    # A concurrent revoke commits first.
    async with sessions() as s:
        await PostgresApiKeyRepository(s).revoke(key.key_id, NOW)
        await s.commit()

    # The edit, which read the key before the revoke, now tries to land.
    async with sessions() as s:
        updated = await PostgresApiKeyRepository(s).update_settings(key.key_id, {"name": "renamed"})
        await s.commit()

    async with sessions() as s:
        stored = await PostgresApiKeyRepository(s).get_by_key_id(key.key_id)

    assert updated is False
    assert stored is not None
    assert stored.revoked_at is not None  # revocation intact
    assert stored.name == "ci"  # the edit did not land


async def test_a_targeted_profile_update_does_not_revert_a_concurrent_disable(
    database_url: str,
) -> None:
    """The user equivalent: renaming an account must not write back the
    `disabled_at` it read as None over a disable that landed in between."""
    sessions = make_session_factory(database_url)
    user = User(id=str(uuid.uuid4()), login="u@example.org", display_name="U", role=Role.USER)
    async with sessions() as s:
        await PostgresUserRepository(s).save(user)
        await s.commit()

    async with sessions() as s:
        await PostgresUserRepository(s).set_disabled(user.id, NOW)
        await s.commit()

    async with sessions() as s:
        await PostgresUserRepository(s).update_profile(user.id, display_name="Renamed", role="user")
        await s.commit()

    async with sessions() as s:
        stored = await PostgresUserRepository(s).get(user.id)

    assert stored is not None
    assert stored.disabled_at is not None  # disable intact
    assert stored.display_name == "Renamed"  # the rename still landed
