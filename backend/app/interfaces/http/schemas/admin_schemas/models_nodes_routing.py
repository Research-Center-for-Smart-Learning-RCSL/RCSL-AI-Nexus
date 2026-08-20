"""Admin models nodes routing schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities.model import Model, RuntimeKind
from app.domain.entities.node import Node
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.ports.infrastructure_ports import JobStatus

ALIAS_PATTERN = r"^[a-z0-9-]+$"
REF_PATTERN = r"^[A-Za-z0-9._:/-]+$"


class ResourceProfileBody(BaseModel):
    memory_gb: float = Field(gt=0)
    context_length: int = Field(gt=0)


class ModelResponse(BaseModel):
    id: str
    alias: str
    ref: str
    runtime: str
    node_id: str
    state: str
    capabilities: list[str]
    resource_profile: ResourceProfileBody

    observed_state: str | None
    """What the runtime last reported holding, where `state` is the
    platform's intent. Null when the heartbeat has not observed the model, or
    the runtime cannot say (MLX)."""
    observed_memory_gb: float | None
    observed_at: datetime | None

    @classmethod
    def of(cls, model: Model) -> ModelResponse:
        return cls(
            id=model.id,
            alias=model.alias,
            ref=model.ref,
            runtime=model.runtime.value,
            node_id=model.node_id,
            state=model.state.value,
            # Sorted so the list is stable between requests; the domain holds a
            # frozenset, whose iteration order is not.
            capabilities=sorted(model.capabilities),
            resource_profile=ResourceProfileBody(
                memory_gb=model.resource_profile.memory_gb,
                context_length=model.resource_profile.context_length,
            ),
            observed_state=model.observed_state.value if model.observed_state else None,
            observed_memory_gb=model.observed_memory_gb,
            observed_at=model.observed_at,
        )


class CreateModelRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=64, pattern=ALIAS_PATTERN)
    ref: str = Field(min_length=1, max_length=255, pattern=REF_PATTERN)
    runtime: RuntimeKind
    node_id: str = Field(min_length=1, max_length=36)
    capabilities: list[str] = Field(min_length=1)
    resource_profile: ResourceProfileBody


class UpdateModelRequest(BaseModel):
    alias: str | None = Field(default=None, min_length=1, max_length=64, pattern=ALIAS_PATTERN)
    ref: str | None = Field(default=None, min_length=1, max_length=255, pattern=REF_PATTERN)
    runtime: RuntimeKind | None = None
    node_id: str | None = Field(default=None, min_length=1, max_length=36)
    capabilities: list[str] | None = Field(default=None, min_length=1)
    resource_profile: ResourceProfileBody | None = None


class NodeResponse(BaseModel):
    id: str
    name: str
    address: str
    status: str
    total_memory_gb: float
    runtimes: list[str]

    @classmethod
    def of(cls, node: Node) -> NodeResponse:
        return cls(
            id=node.id,
            name=node.name,
            address=node.address,
            status=node.status.value,
            total_memory_gb=node.total_memory_gb,
            runtimes=sorted(r.value for r in node.runtimes),
        )


class CreateNodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    address: str = Field(min_length=1, max_length=255)
    """A tailnet address. The authoritative check is the egress guard in the use
    case (security.md §7.2); this bound only keeps an absurd value from reaching
    it. Status is deliberately absent: it is observed by probing, never set from
    the form."""

    total_memory_gb: float = Field(gt=0)
    runtimes: list[RuntimeKind] = Field(min_length=1)


class UpdateNodeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    total_memory_gb: float | None = Field(default=None, gt=0)
    runtimes: list[RuntimeKind] | None = Field(default=None, min_length=1)


class DownloadJobResponse(BaseModel):
    job_id: str
    model_id: str
    state: str
    progress: float | None
    bytes_downloaded: int | None
    bytes_total: int | None
    message: str | None

    @classmethod
    def of(cls, status: JobStatus) -> DownloadJobResponse:
        return cls(
            job_id=status.job_id,
            # `target` is the generic name on the port; this endpoint only ever
            # carries downloads, so it is spelled for its one caller.
            model_id=status.target or "",
            state=status.state,
            progress=status.progress,
            bytes_downloaded=status.completed_bytes,
            bytes_total=status.total_bytes,
            message=status.message,
        )


class RequirementBody(BaseModel):
    node_status: list[str] = Field(default_factory=list)
    model_state: list[str] = Field(default_factory=list)
    min_free_memory_gb: float | None = None


class RoutingCandidateBody(BaseModel):
    model_alias: str = Field(min_length=1, max_length=128)
    priority: int
    require: RequirementBody = Field(default_factory=RequirementBody)


class RoutingPolicyResponse(BaseModel):
    capability: str
    candidates: list[RoutingCandidateBody]
    thinking: bool | None = None
    """Null means the capability takes the deployment default."""

    @classmethod
    def of(cls, policy: RoutingPolicy) -> RoutingPolicyResponse:
        return cls(
            capability=policy.capability,
            thinking=policy.thinking,
            candidates=[
                RoutingCandidateBody(
                    model_alias=c.model_alias,
                    priority=c.priority,
                    require=RequirementBody(
                        node_status=sorted(s.value for s in c.require.node_status),
                        model_state=sorted(s.value for s in c.require.model_state),
                        min_free_memory_gb=c.require.min_free_memory_gb,
                    ),
                )
                for c in policy.candidates
            ],
        )


class SaveRoutingPolicyRequest(BaseModel):
    candidates: list[RoutingCandidateBody] = Field(min_length=1)
    thinking: bool | None = Field(
        default=None,
        description=(
            "Whether a request naming this capability deliberates when it says "
            "nothing about it. Null takes the deployment default. `false` is "
            "what an agent client wants: it pays the deliberation cost again on "
            "every tool round trip, and a thinking model can spend a whole "
            "token budget without answering."
        ),
    )


class GatewayInfoResponse(BaseModel):
    """What the UI needs in order to explain how to use a key."""

    base_url: str
    """Origin of the inference API, without a trailing slash. From
    configuration, because the admin entrance answering this request is on a
    different host from the one being described."""

    capabilities: list[str]
    """Capability names a routing policy currently serves, which is what the
    `model` field of a request takes. A capability absent here can be issued
    on a key but will answer `no_available_model` until a policy names it."""


class DashboardResponse(BaseModel):
    models_total: int
    models_loaded: int
    nodes_online: int
    nodes_total: int
    api_keys_active: int
    users_total: int
    requests_last_24h: int
    tokens_last_24h: int
