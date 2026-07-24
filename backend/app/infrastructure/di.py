"""Composition root.

The one place that decides which adapter satisfies which port. Swapping a
runtime, or pointing the registry at a different store, is a change here plus
a new adapter file; no use case and no router moves.

FastAPI dependencies are thin wrappers around these builders so that the
wiring stays readable in one file rather than spreading across routers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.cache.redis_adapter import InMemoryCache, RedisCache
from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresInvitationRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
    PostgresUsageRepository,
    PostgresUserRepository,
)
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.model import RuntimeKind
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.services.api_key_service import ApiKeyService
from app.domain.services.memory_budget_service import MemoryBudgetService
from app.domain.services.routing_service import RoutingService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import session_scope
from app.shared.clock import SystemClock

SettingsDep = Annotated[Settings, Depends(get_settings)]


# --- process-wide singletons ---------------------------------------------
#
# Held on app.state rather than as module globals, so a test can build an app
# with different wiring without leaking into the next test.


def build_runtimes(settings: Settings) -> dict[RuntimeKind, ModelRuntimePort]:
    """Only Ollama in Phase 1.

    Adding vLLM or MLX means one more entry and one more adapter file. That
    the use cases need no change is the payoff the hexagonal layering was
    chosen for, so it is worth keeping this list as the only place that knows.
    """
    return {
        RuntimeKind.OLLAMA: OllamaAdapter(
            base_url=settings.ollama_base_url,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
    }


def build_concurrency_limiter(settings: Settings) -> SemaphoreConcurrencyLimiter:
    return SemaphoreConcurrencyLimiter(settings.max_concurrent_inference)


def build_api_key_service(settings: Settings) -> ApiKeyService:
    """Peppers are ordered: the first signs new keys, the rest are still
    accepted, which is what allows a rotation to be staged rather than
    invalidating every key at once."""
    peppers = [settings.api_key_pepper.encode()]
    if settings.api_key_pepper_previous:
        peppers.append(settings.api_key_pepper_previous.encode())
    return ApiKeyService(peppers=tuple(peppers))


def build_cache(settings: Settings) -> CachePort:
    if settings.cache_backend == "memory":
        return InMemoryCache()
    return RedisCache(settings.redis_url, settings.redis_password)


def build_authorization() -> AuthorizationPort:
    return RoleAuthorization()


# --- per-request dependencies --------------------------------------------


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_runtimes(request: Request) -> dict[RuntimeKind, ModelRuntimePort]:
    return request.app.state.runtimes  # type: ignore[no-any-return]


def get_concurrency(request: Request) -> SemaphoreConcurrencyLimiter:
    return request.app.state.concurrency  # type: ignore[no-any-return]


def get_api_key_service(request: Request) -> ApiKeyService:
    return request.app.state.api_key_service  # type: ignore[no-any-return]


def get_cache(request: Request) -> CachePort:
    return request.app.state.cache  # type: ignore[no-any-return]


def get_api_key_repository(session: SessionDep) -> PostgresApiKeyRepository:
    return PostgresApiKeyRepository(session)


def get_usage_repository(session: SessionDep) -> PostgresUsageRepository:
    """A distinct dependency from the key repository.

    They were previously conflated behind a `getattr` fallback that returned
    zero when the method was missing, so the quota check silently never ran
    against the real adapter while passing against a test stub.
    """
    return PostgresUsageRepository(session)


def get_user_repository(session: SessionDep) -> PostgresUserRepository:
    return PostgresUserRepository(session)


def get_invitation_repository(session: SessionDep) -> PostgresInvitationRepository:
    return PostgresInvitationRepository(session)


def get_model_repository(session: SessionDep) -> PostgresModelRepository:
    return PostgresModelRepository(session)


def get_node_repository(session: SessionDep) -> PostgresNodeRepository:
    return PostgresNodeRepository(session)


def build_route_chat_request(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> RouteChatRequest:
    return RouteChatRequest(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        usage=PostgresUsageRepository(session),
        runtimes=request.app.state.runtimes,
        routing=RoutingService(),
        concurrency=request.app.state.concurrency,
        authz=request.app.state.authz,
        clock=SystemClock(),
        max_tokens_ceiling=settings.max_tokens_ceiling,
        max_context_chars=settings.max_context_length * 4,
    )


RouteChatRequestDep = Annotated[RouteChatRequest, Depends(build_route_chat_request)]
MemoryBudgetDep = Annotated[MemoryBudgetService, Depends(MemoryBudgetService)]
