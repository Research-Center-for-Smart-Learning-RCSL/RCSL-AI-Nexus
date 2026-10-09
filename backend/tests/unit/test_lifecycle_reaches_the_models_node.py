"""Lifecycle calls go to the runtime of the model's own node (PR4b on #24).

With node agents enabled that runtime is the node's agent, and the by-kind
adapter refuses; resolving by node is what makes load, unload and download
reach the agent at all. A mapping that answers per node stands in for
`RuntimeDirectory` here.
"""

from __future__ import annotations

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.download_model import DownloadModel
from app.domain.entities.model import ModelState, RuntimeKind
from app.domain.entities.node import Node
from app.domain.ports.model_runtime_port import ModelRuntimePort
from tests.unit.fakes import FakeAudit, FakeModels, FakeRuntime, FakeStateCommitter
from tests.unit.manage_models_fixtures import ADMIN, NODE, Harness, make_model
from tests.unit.test_download_model import UPDATES, FakeJobs


class PerNode(dict[RuntimeKind, ModelRuntimePort]):
    def __init__(self, by_kind: ModelRuntimePort, on_node: ModelRuntimePort) -> None:
        super().__init__({RuntimeKind.OLLAMA: by_kind})
        self.on_node = on_node
        self.asked: list[str | None] = []

    def for_node(self, node: Node | None, kind: RuntimeKind) -> ModelRuntimePort | None:
        self.asked.append(node.id if node else None)
        return self.on_node


async def test_load_and_unload_use_the_models_node() -> None:
    by_kind, on_node = FakeRuntime(), FakeRuntime()
    harness = Harness([make_model(state=ModelState.DOWNLOADED)])
    runtimes = PerNode(by_kind, on_node)
    harness.use_case._runtimes = runtimes  # noqa: SLF001 - the seam under test

    await harness.use_case.load(ADMIN, "m1")
    harness.models.rows["m1"] = make_model(state=ModelState.LOADED)
    await harness.use_case.unload(ADMIN, "m1")

    assert runtimes.asked == [NODE.id, NODE.id]
    assert on_node.loaded and on_node.unloaded
    assert not by_kind.loaded and not by_kind.unloaded


async def test_a_download_pulls_on_the_models_node() -> None:
    models = FakeModels([make_model(state=ModelState.DOWNLOADING, node_id=NODE.id)])
    by_kind, on_node = FakeRuntime(), FakeRuntime(pull_updates=UPDATES)
    runtimes = PerNode(by_kind, on_node)
    use_case = DownloadModel(
        models=models,
        runtimes=runtimes,
        jobs=FakeJobs(),
        state_committer=FakeStateCommitter(models, {NODE.id: NODE}),
        authz=RoleAuthorization(),
        audit=FakeAudit(),
    )

    await use_case.run("m1", "job-1")

    assert runtimes.asked == [NODE.id]
    assert models.rows["m1"].state is ModelState.DOWNLOADED
    assert on_node.pull_closed and not by_kind.pull_closed
