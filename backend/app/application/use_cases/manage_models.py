"""The model registry, and the lifecycle operations on it.

This is the highest-risk surface in the platform after the runtime itself: a
model reference reaches an adapter that talks to a process running natively on
the host. The reference is therefore validated here, at registration, as well
as inside the adapter. Two checks on the same value is not redundancy worth
removing; the adapter's protects the runtime call, this one stops a reference
that can never work from being stored at all.

Validation goes through the runtime, not a shared helper, because what counts
as a reference differs by runtime. See `ModelRuntimePort.validate_ref`.

See docs/architecture/security.md section 7.1.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node
from app.domain.exceptions import (
    ModelNotFoundError,
    ModelStateConflictError,
    NodeNotFoundError,
    RuntimeUnavailableError,
)
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import (
    ModelRepositoryPort,
    NodeRepositoryPort,
    RoutingPolicyRepositoryPort,
)
from app.domain.ports.security_ports import AuditPort, AuthorizationPort
from app.domain.services.memory_budget_service import MemoryBudgetService

DELETABLE_STATES = frozenset({ModelState.NOT_DOWNLOADED, ModelState.DOWNLOADED, ModelState.ERROR})
"""Anything mid-transition is excluded. Deleting a row while a download or a
load is in flight leaves the runtime holding something the registry has
forgotten about, which no later operation can reach."""


class ManageModels:
    def __init__(
        self,
        models: ModelRepositoryPort,
        nodes: NodeRepositoryPort,
        policies: RoutingPolicyRepositoryPort,
        runtimes: dict[RuntimeKind, ModelRuntimePort],
        budget: MemoryBudgetService,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._models = models
        self._nodes = nodes
        self._policies = policies
        self._runtimes = runtimes
        self._budget = budget
        self._authz = authz
        self._audit = audit

    async def list_all(self, actor: Actor) -> list[Model]:
        self._authz.require(actor, Scope.MODEL_READ)
        return await self._models.list_all()

    async def get(self, actor: Actor, model_id: str) -> Model:
        self._authz.require(actor, Scope.MODEL_READ)
        return await self._require(model_id)

    async def register(
        self,
        actor: Actor,
        *,
        alias: str,
        ref: str,
        runtime: RuntimeKind,
        node_id: str,
        capabilities: frozenset[str],
        resource_profile: ResourceProfile,
    ) -> Model:
        self._authz.require(actor, Scope.MODEL_WRITE)

        await self._require_node(node_id)
        # Raises InvalidModelReferenceError, which the handler maps to 400.
        # The runtime is resolved first, because it owns the grammar.
        (await self._require_runtime(runtime)).validate_ref(ref)

        if await self._models.get_by_alias(alias) is not None:
            raise ModelStateConflictError(detail=f"alias {alias} is already registered")

        model = Model(
            id=str(uuid.uuid4()),
            alias=alias,
            ref=ref,
            runtime=runtime,
            node_id=node_id,
            # Registration records intent. Whether the weights are present is
            # discovered by downloading, not asserted by whoever filled the
            # form, so a new entry always starts here.
            state=ModelState.NOT_DOWNLOADED,
            capabilities=capabilities,
            resource_profile=resource_profile,
        )
        await self._models.save(model)
        await self._audit.record(
            actor, "model.registered", target=model.id, detail={"alias": alias, "ref": ref}
        )
        return model

    async def update(
        self,
        actor: Actor,
        model_id: str,
        *,
        alias: str | None = None,
        ref: str | None = None,
        runtime: RuntimeKind | None = None,
        node_id: str | None = None,
        capabilities: frozenset[str] | None = None,
        resource_profile: ResourceProfile | None = None,
    ) -> Model:
        self._authz.require(actor, Scope.MODEL_WRITE)
        model = await self._require(model_id)

        if node_id is not None:
            await self._require_node(node_id)
        if ref is not None:
            # Checked against the runtime the model will have after the edit,
            # not the one it has now: changing both at once must not validate
            # the new reference against the old grammar.
            adapter = await self._require_runtime(runtime or model.runtime)
            adapter.validate_ref(ref)
        elif runtime is not None:
            await self._require_runtime(runtime)

        if alias is not None and alias != model.alias:
            if await self._models.get_by_alias(alias) is not None:
                raise ModelStateConflictError(detail=f"alias {alias} is already registered")
            # Routing policies bind to the alias, so renaming a model silently
            # detaches every policy pointing at it. Refused rather than
            # cascaded: rewriting policies as a side effect of a rename is not
            # something an operator editing a form is asking for.
            if await self._referenced_by_policy(model.alias):
                raise ModelStateConflictError(
                    detail=f"alias {model.alias} is bound by a routing policy"
                )

        if model.state is not ModelState.NOT_DOWNLOADED and (
            (ref is not None and ref != model.ref)
            or (runtime is not None and runtime is not model.runtime)
            or (node_id is not None and node_id != model.node_id)
        ):
            # These three name what the runtime has on disk. Changing them
            # under a downloaded or loaded model makes the registry describe
            # something that is not there.
            raise ModelStateConflictError(
                detail=f"model {model.id} is {model.state}; unload and delete to repoint it"
            )

        updated = replace(
            model,
            alias=alias if alias is not None else model.alias,
            ref=ref if ref is not None else model.ref,
            runtime=runtime if runtime is not None else model.runtime,
            node_id=node_id if node_id is not None else model.node_id,
            capabilities=capabilities if capabilities is not None else model.capabilities,
            resource_profile=(
                resource_profile if resource_profile is not None else model.resource_profile
            ),
        )
        await self._models.save(updated)
        await self._audit.record(actor, "model.updated", target=model.id)
        return updated

    async def delete(self, actor: Actor, model_id: str) -> None:
        self._authz.require(actor, Scope.MODEL_WRITE)
        model = await self._require(model_id)

        if model.state not in DELETABLE_STATES:
            raise ModelStateConflictError(
                detail=f"model {model.id} is {model.state}; unload it first"
            )

        if await self._referenced_by_policy(model.alias):
            # No foreign key enforces this: policies bind to the alias, which
            # is a string. Without the check, deleting a model leaves a policy
            # whose only candidate no longer exists, and the failure surfaces
            # as inference returning "no available model" with nothing in the
            # registry to explain why.
            raise ModelStateConflictError(
                detail=f"alias {model.alias} is bound by a routing policy"
            )

        await self._models.delete(model.id)
        await self._audit.record(
            actor, "model.deleted", target=model.id, detail={"alias": model.alias}
        )

    async def load(self, actor: Actor, model_id: str) -> Model:
        """Refused when the node's memory budget would be exceeded.

        A refusal rather than a warning: on unified memory an over-commit does
        not fail cleanly, it drives the machine into swap and takes every other
        model down with it.
        """
        self._authz.require(actor, Scope.MODEL_WRITE)
        model = await self._require(model_id)

        if model.state is ModelState.LOADED:
            return model
        if model.state is not ModelState.DOWNLOADED:
            raise ModelStateConflictError(
                detail=f"model {model.id} is {model.state}; it must be downloaded first"
            )

        node = await self._require_node(model.node_id)
        runtime = await self._require_runtime(model.runtime)

        self._budget.assert_can_load(model, node, await self._models.list_loaded(node.id))

        # LOADING is written before the call so a concurrent load sees the
        # transition rather than a downloaded model it can start again.
        await self._models.set_state(model.id, ModelState.LOADING)
        try:
            await runtime.load(model.ref)
        except Exception:
            await self._models.set_state(model.id, ModelState.ERROR)
            await self._audit.record(actor, "model.loaded", target=model.id, outcome="failed")
            raise

        await self._models.set_state(model.id, ModelState.LOADED)
        await self._audit.record(actor, "model.loaded", target=model.id)
        return replace(model, state=ModelState.LOADED)

    async def unload(self, actor: Actor, model_id: str) -> Model:
        self._authz.require(actor, Scope.MODEL_WRITE)
        model = await self._require(model_id)

        if model.state is not ModelState.LOADED:
            raise ModelStateConflictError(detail=f"model {model.id} is {model.state}, not loaded")

        runtime = await self._require_runtime(model.runtime)
        await self._models.set_state(model.id, ModelState.UNLOADING)
        try:
            await runtime.unload(model.ref)
        except Exception:
            # Deliberately back to LOADED, not ERROR. The unload failed, so as
            # far as anyone knows the weights are still resident and the memory
            # budget must keep counting them.
            await self._models.set_state(model.id, ModelState.LOADED)
            await self._audit.record(actor, "model.unloaded", target=model.id, outcome="failed")
            raise

        await self._models.set_state(model.id, ModelState.DOWNLOADED)
        await self._audit.record(actor, "model.unloaded", target=model.id)
        return replace(model, state=ModelState.DOWNLOADED)

    async def _require(self, model_id: str) -> Model:
        model = await self._models.get(model_id)
        if model is None:
            raise ModelNotFoundError(detail=f"no model {model_id}")
        return model

    async def _require_node(self, node_id: str) -> Node:
        node = await self._nodes.get(node_id)
        if node is None:
            raise NodeNotFoundError(detail=f"no node {node_id}")
        return node

    async def _require_runtime(self, runtime: RuntimeKind) -> ModelRuntimePort:
        adapter = self._runtimes.get(runtime)
        if adapter is None:
            # Registering against a runtime this build has no adapter for
            # produces a row that can never be downloaded or loaded, and the
            # failure would otherwise appear much later as a KeyError.
            raise RuntimeUnavailableError(detail=f"no adapter for runtime {runtime}")
        return adapter

    async def _referenced_by_policy(self, alias: str) -> bool:
        return any(
            candidate.model_alias == alias
            for policy in await self._policies.list_all()
            for candidate in policy.candidates
        )
