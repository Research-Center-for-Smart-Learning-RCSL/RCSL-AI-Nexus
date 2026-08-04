"""The node heartbeat sweep.

The one behaviour worth pinning: status is written only where the probe observed
a change, so both admin entrances running the loop do not churn the table with
identical writes every interval.
"""

from __future__ import annotations

from app.domain.entities.model import (
    Model,
    ModelState,
    ResourceProfile,
    RuntimeKind,
    RuntimeResidency,
)
from app.domain.entities.node import Node, NodeStatus
from app.infrastructure.heartbeat import observe_models, sweep
from tests.unit.fakes import FakeNodeHealth, FakeRuntime


def _node(node_id: str, status: NodeStatus) -> Node:
    return Node(
        id=node_id,
        name=node_id,
        address="100.64.0.1",
        status=status,
        total_memory_gb=64.0,
        runtimes=frozenset({RuntimeKind.OLLAMA}),
    )


async def test_sweep_writes_only_changed_statuses() -> None:
    nodes = [_node("a", NodeStatus.ONLINE), _node("b", NodeStatus.ONLINE)]
    writes: list[tuple[str, NodeStatus]] = []

    async def source() -> list[Node]:
        return nodes

    async def writer(node_id: str, status: NodeStatus) -> None:
        writes.append((node_id, status))

    # The probe says everyone is offline; both nodes were online, so both move.
    changed = await sweep(FakeNodeHealth(status=NodeStatus.OFFLINE), source, writer)

    assert changed == 2
    assert writes == [("a", NodeStatus.OFFLINE), ("b", NodeStatus.OFFLINE)]


async def test_sweep_is_silent_when_nothing_changed() -> None:
    nodes = [_node("a", NodeStatus.ONLINE)]
    writes: list[tuple[str, NodeStatus]] = []

    async def source() -> list[Node]:
        return nodes

    async def writer(node_id: str, status: NodeStatus) -> None:
        writes.append((node_id, status))

    changed = await sweep(FakeNodeHealth(status=NodeStatus.ONLINE), source, writer)

    assert changed == 0
    assert writes == [], "an unchanged status must not be rewritten every interval"


# --- model residency observation -----------------------------------------


def _model(
    alias: str,
    *,
    state: ModelState = ModelState.LOADED,
    observed: ModelState | None = None,
    observed_gb: float | None = None,
    runtime: RuntimeKind = RuntimeKind.OLLAMA,
    node_id: str = "a",
) -> Model:
    return Model(
        id=f"id-{alias}",
        alias=alias,
        ref=alias,
        runtime=runtime,
        node_id=node_id,
        state=state,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=4.7, context_length=8192),
        observed_state=observed,
        observed_memory_gb=observed_gb,
    )


def _writer(writes: list[tuple[str, ModelState | None, float | None]]):
    async def write(model_id: str, state: ModelState | None, gb: float | None) -> None:
        writes.append((model_id, state, gb))

    return write


async def test_observation_catches_the_registry_lie() -> None:
    """Intent says loaded, the runtime holds nothing but the weights on disk —
    the qwen7b shape from 2026-07-27, standing for hours with nothing to
    correct it."""
    models = [_model("qwen7b", state=ModelState.LOADED)]
    runtime = FakeRuntime(residency=RuntimeResidency(on_disk=frozenset({"qwen7b"})))
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return models

    changed = await observe_models({RuntimeKind.OLLAMA: runtime}, source, _writer(writes), "a")

    assert changed == 1
    assert writes == [("id-qwen7b", ModelState.DOWNLOADED, None)]


async def test_observation_records_the_runtime_own_memory_figure() -> None:
    models = [_model("glm", state=ModelState.LOADED)]
    runtime = FakeRuntime(
        residency=RuntimeResidency(resident={"glm": 38.0}, on_disk=frozenset({"glm"}))
    )
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return models

    changed = await observe_models({RuntimeKind.OLLAMA: runtime}, source, _writer(writes), "a")

    assert changed == 1
    assert writes == [("id-glm", ModelState.LOADED, 38.0)]


async def test_unchanged_observation_is_rewritten_but_not_counted() -> None:
    """`observed_at` has to mean *last observed*, so a steady observation is
    restamped rather than skipped.

    It was skipped until 2026-08-04, and the model rows then read `2026-07-30`
    for five days while the sweep ran every thirty seconds — so a model
    observed steadily for five days and a heartbeat that died five days ago
    were the same row, with no way to tell which. The churn that skipping
    avoided was also being paid twice at the time, because both admin
    entrances ran the sweep; only the tailnet one does now.

    Still not *counted*: the return value answers "what moved", and a
    transition buried under thirty restamps a minute is a transition nobody
    sees.
    """
    models = [_model("glm", observed=ModelState.LOADED, observed_gb=38.0)]
    runtime = FakeRuntime(
        residency=RuntimeResidency(resident={"glm": 38.0}, on_disk=frozenset({"glm"}))
    )
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return models

    assert await observe_models({RuntimeKind.OLLAMA: runtime}, source, _writer(writes), "a") == 0
    assert writes == [("id-glm", ModelState.LOADED, 38.0)], "restamped, so the row stays readable"


async def test_unobservable_runtime_clears_a_stale_observation() -> None:
    """A claim that cannot be re-checked must not keep the authority of one
    that just was: when the runtime stops answering, the observation goes back
    to null and readers fall back to intent."""
    models = [_model("glm", observed=ModelState.LOADED, observed_gb=38.0)]
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return models

    changed = await observe_models(
        {RuntimeKind.OLLAMA: FakeRuntime(residency=None)}, source, _writer(writes), "a"
    )

    assert changed == 1
    assert writes == [("id-glm", None, None)]


async def test_a_raising_runtime_reads_as_unobservable_not_as_absent() -> None:
    """The check that can only return one answer, again: a network blip must
    not read as "nothing is resident" and mark every model unloaded."""
    models = [_model("glm", state=ModelState.LOADED, observed=ModelState.LOADED)]
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return models

    changed = await observe_models(
        {RuntimeKind.OLLAMA: FakeRuntime(fail_on="residency")}, source, _writer(writes), "a"
    )

    assert changed == 1
    assert writes == [("id-glm", None, None)], "unreachable clears, it must never assert absence"


async def test_a_runtime_with_no_adapter_leaves_no_observation() -> None:
    """An MLX model in a build with no MLX adapter, or any runtime the sweep
    cannot ask: observation stays wherever it is only if already null."""
    models = [_model("mlx-model", runtime=RuntimeKind.MLX, observed=None)]
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return models

    assert await observe_models({}, source, _writer(writes), "a") == 0
    assert writes == []


async def test_another_node_s_models_are_left_unobserved_not_reported_absent() -> None:
    """The adapters point at the configured host runtime, never at
    `node.address`, so a second node's residency is not something this sweep can
    see. Writing `not_downloaded` would be a confident wrong answer — and since
    routing ranks observation over intent, it would refuse every model on that
    node and make the memory budget count its rows against the local runtime."""
    local = _model("here")
    remote = _model("there", node_id="b")
    runtime = FakeRuntime(
        residency=RuntimeResidency(resident={"here": 4.0}, on_disk=frozenset({"here"}))
    )
    writes: list[tuple[str, ModelState | None, float | None]] = []

    async def source() -> list[Model]:
        return [local, remote]

    changed = await observe_models({RuntimeKind.OLLAMA: runtime}, source, _writer(writes), "a")

    assert changed == 1, "only the local model's observation moved"
    assert writes == [("id-here", ModelState.LOADED, 4.0)]
    assert all(w[0] != "id-there" for w in writes), "a remote model must not be reported absent"
