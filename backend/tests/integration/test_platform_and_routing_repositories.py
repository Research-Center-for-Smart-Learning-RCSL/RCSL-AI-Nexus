from __future__ import annotations

from dataclasses import replace

import pytest

from app.adapters.persistence.repositories import (
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
)
from app.domain.entities.model import ModelState, RuntimeKind
from app.domain.entities.node import NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from tests.integration.repository_fixtures import (
    TEST_DATABASE_URL,
    _model,
    _node,
)

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.repository_fixtures",)


async def test_node_round_trip(session) -> None:
    repo = PostgresNodeRepository(session)
    await repo.save(_node())
    await session.flush()

    stored = await repo.get("n1")
    assert stored is not None
    # frozenset of enums survives the trip through a JSON array of strings
    assert stored.runtimes == frozenset({RuntimeKind.OLLAMA, RuntimeKind.MLX})
    assert stored.status is NodeStatus.ONLINE
    assert stored.total_memory_gb == 64.0


async def test_model_round_trip_and_alias_lookup(session) -> None:
    await PostgresNodeRepository(session).save(_node())
    await session.flush()
    repo = PostgresModelRepository(session)
    await repo.save(_model())
    await session.flush()

    stored = await repo.get_by_alias("primary")
    assert stored is not None
    assert stored.capabilities == frozenset({"chat", "code"})
    # resource_profile is flattened into two columns and must reassemble
    assert stored.resource_profile.memory_gb == 18.5
    assert stored.resource_profile.context_length == 32768


async def test_list_loaded_filters_by_state_and_node(session) -> None:
    await PostgresNodeRepository(session).save(_node())
    await PostgresNodeRepository(session).save(_node("n2"))
    await session.flush()
    repo = PostgresModelRepository(session)

    loaded = _model("loaded-here", "n1")
    elsewhere = _model("loaded-elsewhere", "n2")
    # `replace`, not `__dict__`: the entities are slotted dataclasses.
    idle = replace(_model("idle", "n1"), state=ModelState.DOWNLOADED)

    for entity in (loaded, elsewhere, idle):
        await repo.save(entity)
    await session.flush()

    aliases = {m.alias for m in await repo.list_loaded("n1")}
    assert aliases == {"loaded-here"}


async def test_an_intent_write_clears_the_observation_beside_it(session) -> None:
    """The pairing `set_state` promises, against the real UPDATE.

    Every reader ranks the observation over the intent, so an observation taken
    before a transition would outrank the transition itself: a model loaded a
    moment ago would keep routing as `downloaded` until the next sweep, and a
    `model_state: [loaded]` policy with one candidate would answer 503 for
    resident weights. This is pinned here rather than in the unit suite because
    the use cases reach `set_state` only after a state committer has already
    written — so a unit test of `load` passes whether or not this clause exists.
    """
    await PostgresNodeRepository(session).save(_node())
    await session.flush()
    repo = PostgresModelRepository(session)
    model = replace(_model(), state=ModelState.DOWNLOADED)
    await repo.save(model)
    await session.flush()

    await repo.set_observed(model.id, ModelState.DOWNLOADED, None)
    await session.flush()
    observed = await repo.get(model.id)
    assert observed is not None and observed.observed_at is not None

    await repo.set_state(model.id, ModelState.LOADED)
    await session.flush()

    stored = await repo.get(model.id)
    assert stored is not None
    assert stored.state is ModelState.LOADED
    assert stored.observed_state is None, "an observation predating the write must not survive it"
    assert stored.observed_memory_gb is None
    assert stored.observed_at is None, "the timestamp goes with the observation it dated"


async def test_an_unobservable_runtime_clears_rather_than_asserting_absence(session) -> None:
    """`set_observed(None, None)` is the heartbeat saying "could not ask", which
    must not read as "nothing is resident": the timestamp is cleared with it, so
    no reader can mistake a stale observation for a fresh one."""
    await PostgresNodeRepository(session).save(_node())
    await session.flush()
    repo = PostgresModelRepository(session)
    model = _model()
    await repo.save(model)
    await session.flush()

    await repo.set_observed(model.id, ModelState.LOADED, 5.7)
    await session.flush()
    seen = await repo.get(model.id)
    assert seen is not None and seen.observed_memory_gb == 5.7

    await repo.set_observed(model.id, None, None)
    await session.flush()

    cleared = await repo.get(model.id)
    assert cleared is not None
    assert cleared.observed_state is None
    assert cleared.observed_at is None
    assert cleared.state is ModelState.LOADED, "intent is untouched by an observation write"


async def test_routing_policy_structured_requirements_round_trip(session) -> None:
    """The requirement document is the part most likely to rot silently.

    It is persisted as JSON and rebuilt field by field, so a mismatch shows up
    as a policy that quietly stops matching rather than as an error.
    """
    repo = PostgresRoutingPolicyRepository(session)
    policy = RoutingPolicy(
        capability="chat",
        candidates=(
            RoutingCandidate(
                model_alias="primary",
                priority=100,
                require=Requirement(
                    node_status=frozenset({NodeStatus.ONLINE}),
                    model_state=frozenset({ModelState.LOADED}),
                    min_free_memory_gb=24.0,
                ),
            ),
            RoutingCandidate(model_alias="fallback", priority=10),
        ),
    )
    await repo.save(policy)
    await session.flush()

    stored = await repo.get("chat")
    assert stored == policy, "requirement document did not survive the round trip"
