"""Dependency providers for shared."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.audit.postgres_audit import PostgresAudit
from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.cache.job_progress import CacheJobProgress
from app.adapters.cache.redis_adapter import InMemoryCache, RedisCache
from app.adapters.crypto.argon2_hasher import Argon2Hasher
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.adapters.crypto.secret_box import FernetSecretBox
from app.adapters.crypto.zxcvbn_policy import ZxcvbnPasswordPolicy
from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresInvitationRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRefusalWriter,
    PostgresUsageRepository,
    PostgresUserRepository,
)
from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.adapters.session.session_store import SessionData, SessionStore
from app.adapters.tokenizer.gguf_token_counter import GgufTokenCounter
from app.domain.entities.actor import Actor
from app.domain.entities.model import RuntimeKind
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.ports.token_counter_port import TokenCounterPort
from app.domain.services.api_key_service import ApiKeyService
from app.domain.services.token_service import TokenService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import get_session_factory, session_scope
from app.shared.clock import SystemClock

SettingsDep = Annotated[Settings, Depends(get_settings)]


def build_runtimes(settings: Settings) -> dict[RuntimeKind, ModelRuntimePort]:
    """The one place that knows which runtimes this build serves.

    Adding MLX cost one entry here and one adapter file, with no use case and no
    interface touched: the payoff the hexagonal layering was chosen for. vLLM
    would be the same, once there is hardware it runs on. See
    adapters/runtime/mlx_adapter.py.
    """
    return {
        RuntimeKind.OLLAMA: OllamaAdapter(
            base_url=settings.ollama_base_url,
            request_timeout_seconds=settings.request_timeout_seconds,
            keep_alive=settings.ollama_keep_alive,
        ),
        RuntimeKind.MLX: MlxAdapter(
            base_url=settings.mlx_base_url,
            request_timeout_seconds=settings.request_timeout_seconds,
            tool_calling_verified=settings.mlx_tool_calling_verified,
        ),
    }


def build_token_counter(settings: Settings) -> TokenCounterPort | None:
    """One counter per process, because it holds one cache per process.

    Built here and kept on `app.state` beside the runtimes and the concurrency
    limiter, for the same reason those are: a tokeniser costs 132 MB for a
    248320-entry vocabulary and a quarter of a second to build, and a
    per-request instance would pay both on every request. Nothing about it is
    per-caller.

    `None` when no model store is configured, which is what a deployment that
    has not mounted one gets. That is a supported shape rather than a
    misconfiguration — MLX-only hosts have no GGUF to read — and it lands the
    platform exactly where it was before 2026-08-17: counting characters, and
    saying so in a log line on the first request to each model.
    """
    if not settings.ollama_models_path:
        return None
    return GgufTokenCounter(
        Path(settings.ollama_models_path),
        cache_size=settings.token_counter_cache_size,
    )


def build_refusal_writer() -> PostgresRefusalWriter:
    """A session factory, not a session, and not for convenience.

    Every row this writes is written while a request is failing, from the
    exception handler that is rendering the failure. The request's own session
    is being rolled back underneath it, so a writer sharing that session would
    record nothing at all — the failure mode `PostgresPromptLogWriter` found on
    a table where it cost some rows, on a table where it would cost all of them.
    """
    return PostgresRefusalWriter(get_session_factory())


def build_concurrency_limiter(settings: Settings) -> SemaphoreConcurrencyLimiter:
    return SemaphoreConcurrencyLimiter(
        settings.max_concurrent_inference,
        queue_wait_seconds=settings.queue_wait_seconds,
    )


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


def build_password_hasher() -> Argon2Hasher:
    """A singleton, because it owns the concurrency limiter that bounds how
    much memory unauthenticated login attempts can occupy at once. One per
    request would make that bound meaningless."""
    return Argon2Hasher()


def build_totp() -> PyotpTotp:
    return PyotpTotp()


def build_secret_box(settings: Settings) -> FernetSecretBox:
    return FernetSecretBox(settings.totp_encryption_key)


def build_password_policy() -> ZxcvbnPasswordPolicy:
    """A singleton so zxcvbn's frequency dictionary is loaded once per process
    rather than on the request that happens to be setting a password."""
    return ZxcvbnPasswordPolicy()


def build_token_service() -> TokenService:
    return TokenService()


def build_session_store(settings: Settings, cache: CachePort) -> SessionStore:
    return SessionStore(
        cache,
        absolute_ttl=settings.session_absolute_ttl_seconds,
        idle_ttl=settings.session_idle_ttl_seconds,
    )


def build_job_progress(cache: CachePort) -> CacheJobProgress:
    return CacheJobProgress(cache)


def build_audit() -> PostgresAudit:
    """Given the session *factory*, not a session.

    Audit rows are written in their own transaction so a failed request still
    records its failure; see adapters/audit/postgres_audit.py.
    """
    return PostgresAudit(get_session_factory(), SystemClock())


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


def current_actor() -> Actor:
    """Overridden per application by its identity resolver. Never called."""
    raise NotImplementedError(
        "No identity resolver installed. create_app must override current_actor."
    )


def current_session() -> SessionData | None:
    """The caller's session, or None on an entrance that has none."""
    return None


def current_tenant_id(actor: Annotated[Actor, Depends(current_actor)]) -> str:
    """The tenant a request acts within, for scoping repositories to it."""
    return actor.tenant_id


TenantIdDep = Annotated[str, Depends(current_tenant_id)]


def get_api_key_repository(session: SessionDep) -> PostgresApiKeyRepository:
    """Unscoped: the gateway authenticates a key by its handle before its tenant
    is known."""
    return PostgresApiKeyRepository.unscoped(session)


def get_usage_repository(session: SessionDep) -> PostgresUsageRepository:
    """A distinct dependency from the key repository.

    They were previously conflated behind a `getattr` fallback that returned
    zero when the method was missing, so the quota check silently never ran
    against the real adapter while passing against a test stub.

    Unscoped: the gateway path stamps the tenant onto the usage record from the
    authenticated actor, so a filter here would be redundant, and the quota read
    is by key handle.
    """
    return PostgresUsageRepository.unscoped(session)


def get_user_repository(session: SessionDep) -> PostgresUserRepository:
    """Unscoped, because the identity resolvers use it to look up the very user
    that becomes the actor: there is no tenant to scope by yet."""
    return PostgresUserRepository.unscoped(session)


def get_user_repository_scoped(
    session: SessionDep, tenant_id: TenantIdDep
) -> PostgresUserRepository:
    """Scoped to the caller's tenant, for handlers that enumerate users (the API
    key list's owner names), so a tenant admin sees only their own."""
    return PostgresUserRepository(session, tenant_id)


def get_invitation_repository(session: SessionDep) -> PostgresInvitationRepository:
    return PostgresInvitationRepository(session)


def get_model_repository(session: SessionDep) -> PostgresModelRepository:
    return PostgresModelRepository(session)


def get_node_repository(session: SessionDep) -> PostgresNodeRepository:
    return PostgresNodeRepository(session)
