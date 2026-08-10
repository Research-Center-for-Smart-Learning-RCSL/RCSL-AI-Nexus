"""Editing the capability-to-model mapping.

**This is the endpoint that makes the gateway work at all.** `RouteChatRequest`
reads a policy from the database to decide what serves a capability; without a
way to write one, every inference request answers "no model is currently
available" and nothing in the UI explains why.

The shape being edited is a closed set of structured fields, never an
expression. Policies are authored through this API and evaluated inside the
gateway process, so an expression evaluator would turn "edit a routing policy"
into "run code in the gateway". Adding a condition means adding a field and a
comparison, which is a reviewable code change rather than a form submission.
See docs/ARCHITECTURE.md section 2.4.
"""

from __future__ import annotations

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.capability import ROUTABLE_CAPABILITIES
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.exceptions import ModelNotFoundError, ModelStateConflictError
from app.domain.ports.repositories import ModelRepositoryPort, RoutingPolicyRepositoryPort
from app.domain.ports.security_ports import AuditPort, AuthorizationPort


class ManageRoutingPolicies:
    def __init__(
        self,
        policies: RoutingPolicyRepositoryPort,
        models: ModelRepositoryPort,
        authz: AuthorizationPort,
        audit: AuditPort,
    ) -> None:
        self._policies = policies
        self._models = models
        self._authz = authz
        self._audit = audit

    async def list_all(self, actor: Actor) -> list[RoutingPolicy]:
        self._authz.require(actor, Scope.ROUTING_READ)
        return await self._policies.list_all()

    async def get(self, actor: Actor, capability: str) -> RoutingPolicy:
        self._authz.require(actor, Scope.ROUTING_READ)
        policy = await self._policies.get(capability)
        if policy is None:
            raise ModelNotFoundError(detail=f"no policy for {capability}")
        return policy

    async def save(
        self,
        actor: Actor,
        capability: str,
        candidates: list[RoutingCandidate],
        thinking: bool | None = None,
    ) -> RoutingPolicy:
        """Upsert. Every candidate alias must already be registered.

        Checked here rather than left to routing, because a policy naming a
        model that does not exist fails at inference time as "no available
        model", which is indistinguishable from every node being busy. The
        operator writing the policy is the one who can fix a typo.

        `thinking=None` leaves the capability on the deployment default, which
        is what every policy written before the field existed does. It is not
        validated against the candidates: whether a model deliberates at all is
        the runtime's business, and Ollama refuses `think: true` for a model
        that cannot rather than this layer having to know which can.
        """
        self._authz.require(actor, Scope.ROUTING_WRITE)

        # The routable set, which is the wider of the two: a policy may be
        # written for anything the platform can serve, including capabilities
        # that are deliberately not sold to API key holders (`assist`).
        # `ManageApiKeys` checks the narrower issuable set, and the two used to
        # be one set consulted from only one of them — a policy for `chatt`
        # stored and audited cleanly, while a key for `chatt` was refused as an
        # unknown capability, so nothing could ever route to it and it was
        # advertised as servable by `GET /v1/models` to every caller.
        if capability not in ROUTABLE_CAPABILITIES:
            raise ModelStateConflictError(
                detail=f"unknown capability {capability!r}; expected one of "
                f"{sorted(ROUTABLE_CAPABILITIES)}"
            )

        if not candidates:
            raise ModelStateConflictError(detail=f"policy {capability} has no candidates")

        for candidate in candidates:
            if await self._models.get_by_alias(candidate.model_alias) is None:
                raise ModelNotFoundError(detail=f"no model with alias {candidate.model_alias}")

        # Sorted here so the stored order is the evaluation order, and nobody
        # has to know whether routing sorts before it reads.
        ordered = tuple(sorted(candidates, key=lambda c: c.priority))
        policy = RoutingPolicy(capability=capability, candidates=ordered, thinking=thinking)

        await self._policies.save(policy)
        await self._audit.record(
            actor,
            AuditAction.ROUTING_POLICY_SAVED,
            target=capability,
            detail={
                "candidates": ",".join(c.model_alias for c in ordered),
                # Recorded because it changes what every caller of this
                # capability gets, and the change is invisible in the candidate
                # list an audit reader would otherwise be looking at.
                "thinking": "default" if thinking is None else str(thinking).lower(),
            },
        )
        return policy

    async def delete(self, actor: Actor, capability: str) -> None:
        self._authz.require(actor, Scope.ROUTING_WRITE)

        if await self._policies.get(capability) is None:
            raise ModelNotFoundError(detail=f"no policy for {capability}")

        await self._policies.delete(capability)
        await self._audit.record(actor, AuditAction.ROUTING_POLICY_DELETED, target=capability)
