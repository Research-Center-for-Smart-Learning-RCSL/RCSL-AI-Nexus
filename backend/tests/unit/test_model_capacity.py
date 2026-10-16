"""C4 reads the selected host's declaration without widening counting profiles."""

from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.persistence.mappers.platform_runtime import model_to_domain, model_to_row
from app.adapters.runtime.node_agent_adapter import NodeAgentRuntime
from app.domain.entities.model import ModelState, ResourceProfile
from app.domain.exceptions import ModelStateConflictError
from app.domain.ports.model_runtime_port import declared_context_for
from tests.unit.fakes import FakeRuntime
from tests.unit.manage_models_fixtures import (
    ADMIN,
    PROFILE,
    DeclaringCounter,
    Harness,
    make_model,
)


@pytest.mark.parametrize("declared,validated", [(None, False), (8192, True), (32768, True)])
async def test_registration_records_only_read_capacity(declared, validated) -> None:
    harness = Harness(tokens=DeclaringCounter(declared))
    model = await harness.register()
    assert model.capacity_validated is validated
    stored = await harness.models.get(model.id)
    assert stored is not None and stored.capacity_validated is validated


async def test_registration_above_declared_capacity_never_writes_a_model() -> None:
    harness = Harness(tokens=DeclaringCounter(4096))
    with pytest.raises(ModelStateConflictError, match="exceeds declared maximum 4096"):
        await harness.register()
    assert not await harness.models.list_all()


async def test_update_refuses_an_increased_profile_above_capacity() -> None:
    model = make_model(capacity_validated=True)
    harness = Harness([model], tokens=DeclaringCounter(8192))
    with pytest.raises(ModelStateConflictError, match="exceeds declared maximum 8192"):
        await harness.use_case.update(
            ADMIN, model.id, resource_profile=ResourceProfile(memory_gb=20, context_length=8193)
        )
    assert await harness.models.get(model.id) == model


async def test_repointing_to_an_unresolved_model_invalidates_capacity() -> None:
    model = make_model(state=ModelState.NOT_DOWNLOADED, capacity_validated=True)
    harness = Harness([model], tokens=DeclaringCounter(None))
    updated = await harness.use_case.update(ADMIN, model.id, ref="other:latest")
    assert not updated.capacity_validated


async def test_loading_resolves_capacity_and_retains_it_in_storage() -> None:
    harness = Harness([make_model()], tokens=DeclaringCounter(PROFILE.context_length))
    returned = await harness.use_case.load(ADMIN, "m1")
    stored = await harness.models.get("m1")
    assert returned.capacity_validated
    assert stored is not None and stored.capacity_validated
    assert returned.state is ModelState.LOADED


async def test_loading_without_metadata_does_not_validate_capacity() -> None:
    harness = Harness([make_model(capacity_validated=True)], tokens=DeclaringCounter(None))
    returned = await harness.use_case.load(ADMIN, "m1")
    assert not returned.capacity_validated


async def test_remote_metadata_never_uses_another_hosts_counter() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"declared_context_length": 4096, "manifest_digest": "a"})

    runtime = NodeAgentRuntime(
        "http://selected-node.test", "token", timeout_s=1, transport=httpx.MockTransport(respond)
    )
    local = DeclaringCounter(32768)
    assert await declared_context_for(runtime, "qwen:7b", local) == 4096
    assert not local.asked
    assert str(requests[0].url) == "http://selected-node.test/v1/model-capacity?ref=qwen%3A7b"
    assert requests[0].headers["authorization"] == "Bearer token"


async def test_registration_uses_selected_node_metadata() -> None:
    class RemoteRuntime(FakeRuntime):
        async def declared_context_length(self, ref: str) -> int:
            return 4096

    local = DeclaringCounter(32768)
    harness = Harness(runtime=RemoteRuntime(), tokens=local)
    with pytest.raises(ModelStateConflictError, match="exceeds declared maximum 4096"):
        await harness.register()
    assert not local.asked


async def test_unreachable_remote_metadata_stays_unresolved() -> None:
    async def unavailable(ref: str) -> int:
        raise RuntimeError("node offline")

    local = DeclaringCounter(32768)
    runtime = SimpleNamespace(declared_context_length=unavailable)
    assert await declared_context_for(runtime, "qwen:7b", local) is None
    assert not local.asked


def test_capacity_round_trip_preserves_agent_owned_manifest_pin() -> None:
    model = replace(make_model(), capacity_validated=True, manifest_digest="a" * 64)
    row = model_to_row(model)
    # CRUD writes must not overwrite a concurrently updated agent pin.
    assert "manifest_digest" not in row.__dict__
    row.manifest_digest = model.manifest_digest
    assert model_to_domain(row) == model


async def test_capacity_cache_is_shared_by_calls_but_new_manifest_misses(monkeypatch):
    calls = []
    manifest = "a"

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json={"declared_context_length": 4096, "manifest_digest": manifest}
        )

    runtime = NodeAgentRuntime(
        "http://agent", "token", timeout_s=1, transport=httpx.MockTransport(respond)
    )
    assert await declared_context_for(runtime, "model", None, manifest="a") == 4096
    assert await declared_context_for(runtime, "model", None, manifest="a") == 4096
    assert len(calls) == 1
    manifest = "b"
    assert await declared_context_for(runtime, "model", None, manifest="b") == 4096
    assert len(calls) == 2
    for key, (_, value) in list(runtime._capacities.items()):
        runtime._capacities[key] = (0, value)
    assert await declared_context_for(runtime, "model", None, manifest="b") == 4096
    assert len(calls) == 3


async def test_load_preserves_concurrent_admin_edits_and_does_not_restore_old_observation():
    model = make_model(observed_state=ModelState.DOWNLOADED, observed_memory_gb=3)
    harness = Harness([model], tokens=DeclaringCounter(PROFILE.context_length))

    async def concurrent_edit(ref, **kwargs):
        current = await harness.models.get(model.id)
        await harness.models.save(
            replace(current, alias="renamed", capabilities=frozenset({"assist"}))
        )

    harness.runtime.load = concurrent_edit
    result = await harness.use_case.load(ADMIN, model.id)
    stored = await harness.models.get(model.id)
    assert stored.alias == result.alias == "renamed"
    assert stored.capabilities == frozenset({"assist"})
    assert stored.observed_state is None and stored.observed_memory_gb is None
    assert stored.capacity_validated and stored.state is ModelState.LOADED


async def test_capacity_result_does_not_validate_a_concurrently_changed_profile():
    model = make_model()
    harness = Harness([model], tokens=DeclaringCounter(PROFILE.context_length))

    async def concurrent_edit(ref, **kwargs):
        current = await harness.models.get(model.id)
        await harness.models.save(replace(current, resource_profile=ResourceProfile(20, 16384)))

    harness.runtime.load = concurrent_edit
    await harness.use_case.load(ADMIN, model.id)
    assert not (await harness.models.get(model.id)).capacity_validated
