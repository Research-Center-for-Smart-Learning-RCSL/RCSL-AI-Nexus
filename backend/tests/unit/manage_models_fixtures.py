"""Registry rules and the model lifecycle.

The state machine is where a plausible implementation goes wrong quietly: a
failed load that leaves the row saying `loaded`, a delete that removes the
only candidate a routing policy names, an edit that repoints a model whose
weights are already on disk. None of those raise anything at the time.
"""

from __future__ import annotations

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.manage_models import ManageModels
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.services.memory_budget_service import MemoryBudgetService
from tests.unit.fakes import (
    FakeAudit,
    FakeModels,
    FakeNodes,
    FakePolicies,
    FakeRuntime,
    FakeStateCommitter,
)

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

NODE = Node(
    id="node-1",
    name="studio",
    address="100.64.0.1",
    status=NodeStatus.ONLINE,
    total_memory_gb=100.0,
    runtimes=frozenset({RuntimeKind.OLLAMA}),
)

PROFILE = ResourceProfile(memory_gb=20.0, context_length=8192)


def make_model(**overrides: object) -> Model:
    defaults: dict[str, object] = {
        "id": "m1",
        "alias": "chat-main",
        "ref": "library/qwen2.5:7b",
        "runtime": RuntimeKind.OLLAMA,
        "node_id": NODE.id,
        "state": ModelState.DOWNLOADED,
        "capabilities": frozenset({"chat"}),
        "resource_profile": PROFILE,
    }
    defaults.update(overrides)
    return Model(**defaults)  # type: ignore[arg-type]


class Harness:
    def __init__(
        self,
        models: list[Model] | None = None,
        policies: list[RoutingPolicy] | None = None,
        runtime: FakeRuntime | None = None,
    ) -> None:
        self.models = FakeModels(models or [])
        self.nodes = FakeNodes([NODE])
        self.policies = FakePolicies(policies or [])
        self.audit = FakeAudit()
        self.runtime = runtime or FakeRuntime()

        self.use_case = ManageModels(
            models=self.models,
            nodes=self.nodes,
            policies=self.policies,
            runtimes={RuntimeKind.OLLAMA: self.runtime},
            budget=MemoryBudgetService(),
            state_committer=FakeStateCommitter(self.models),
            authz=RoleAuthorization(),
            audit=self.audit,
        )

    async def register(self, **overrides: object) -> Model:
        kwargs: dict[str, object] = {
            "alias": "chat-main",
            "ref": "library/qwen2.5:7b",
            "runtime": RuntimeKind.OLLAMA,
            "node_id": NODE.id,
            "capabilities": frozenset({"chat"}),
            "resource_profile": PROFILE,
        }
        kwargs.update(overrides)
        return await self.use_case.register(ADMIN, **kwargs)  # type: ignore[arg-type]
