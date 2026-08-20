"""Typed dependency state shared by route-chat stages."""

from __future__ import annotations

from collections.abc import Callable

from app.application.use_cases.list_capabilities import ListCapabilities
from app.domain.entities.model import RuntimeKind
from app.domain.ports.infrastructure_ports import ConcurrencyLimiterPort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import (
    ModelRepositoryPort,
    NodeRepositoryPort,
    PromptLogWriterPort,
    RoutingPolicyRepositoryPort,
    UsageRepositoryPort,
)
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.ports.token_counter_port import TokenCounterPort
from app.domain.services.routing_service import RoutingService
from app.shared.clock import Clock


class RouteChatDependencies:
    _policies: RoutingPolicyRepositoryPort
    _models: ModelRepositoryPort
    _nodes: NodeRepositoryPort
    _usage: UsageRepositoryPort
    _runtimes: dict[RuntimeKind, ModelRuntimePort]
    _routing: RoutingService
    _concurrency: ConcurrencyLimiterPort
    _authz: AuthorizationPort
    _clock: Clock
    _capabilities: ListCapabilities
    _tokens: TokenCounterPort | None
    _prompt_logs: PromptLogWriterPort | None
    _request_id: Callable[[], str | None]
    _max_tokens_ceiling: int
    _max_context_tokens: int
    _generation_deadline_seconds: int
    _thinking_default: bool
    _monotonic: Callable[[], float]
