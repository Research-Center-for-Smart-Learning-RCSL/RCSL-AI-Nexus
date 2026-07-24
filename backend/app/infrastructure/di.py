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

from app.adapters.audit.postgres_audit import PostgresAudit
from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.cache.job_progress import CacheJobProgress
from app.adapters.cache.redis_adapter import InMemoryCache, RedisCache
from app.adapters.crypto.argon2_hasher import Argon2Hasher
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.adapters.crypto.secret_box import FernetSecretBox
from app.adapters.crypto.zxcvbn_policy import ZxcvbnPasswordPolicy
from app.adapters.persistence.model_state import ModelStateCommitter
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
from app.adapters.session.session_store import SessionStore
from app.application.use_cases.accept_invitation import AcceptInvitation
from app.application.use_cases.authenticate_local import AuthenticateLocal
from app.application.use_cases.bootstrap_first_admin import BootstrapFirstAdmin
from app.application.use_cases.download_model import DownloadModel
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.manage_api_keys import ManageApiKeys
from app.application.use_cases.manage_models import ManageModels
from app.application.use_cases.manage_own_account import ManageOwnAccount
from app.application.use_cases.manage_routing_policies import ManageRoutingPolicies
from app.application.use_cases.manage_users import ManageUsers
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.application.use_cases.read_dashboard import ReadDashboard
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.model import RuntimeKind
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.services.api_key_service import ApiKeyService
from app.domain.services.login_throttle import LoginThrottle
from app.domain.services.memory_budget_service import MemoryBudgetService
from app.domain.services.routing_service import RoutingService
from app.domain.services.token_service import TokenService
from app.infrastructure.concurrency import SemaphoreConcurrencyLimiter
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db import get_session_factory, session_scope
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


# --- identity and account management -------------------------------------
#
# All of these hang off `app.state`, which is populated in each entrance's
# lifespan. Reading from there rather than constructing per request is what
# keeps the argon2 concurrency bound and the zxcvbn dictionary load to one
# instance per process.


def get_authorization(request: Request) -> AuthorizationPort:
    return request.app.state.authz  # type: ignore[no-any-return]


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions  # type: ignore[no-any-return]


def get_audit(request: Request) -> PostgresAudit:
    return request.app.state.audit  # type: ignore[no-any-return]


def get_password_hasher(request: Request) -> Argon2Hasher:
    return request.app.state.hasher  # type: ignore[no-any-return]


def get_totp(request: Request) -> PyotpTotp:
    return request.app.state.totp  # type: ignore[no-any-return]


def get_secret_box(request: Request) -> FernetSecretBox:
    return request.app.state.secret_box  # type: ignore[no-any-return]


def get_password_policy(request: Request) -> ZxcvbnPasswordPolicy:
    return request.app.state.password_policy  # type: ignore[no-any-return]


def get_token_service(request: Request) -> TokenService:
    return request.app.state.tokens  # type: ignore[no-any-return]


def build_login_throttle(request: Request) -> LoginThrottle:
    return LoginThrottle(request.app.state.cache)


def build_bootstrap_first_admin(
    request: Request, session: SessionDep, settings: SettingsDep
) -> BootstrapFirstAdmin:
    return BootstrapFirstAdmin(
        users=PostgresUserRepository(session),
        audit=request.app.state.audit,
        authz=request.app.state.authz,
        bootstrap_login=settings.bootstrap_admin_login,
    )


def build_authenticate_local(request: Request, session: SessionDep) -> AuthenticateLocal:
    return AuthenticateLocal(
        users=PostgresUserRepository(session),
        hasher=request.app.state.hasher,
        totp=request.app.state.totp,
        invitations=PostgresInvitationRepository(session),
        tokens=request.app.state.tokens,
        throttle=LoginThrottle(request.app.state.cache),
        secret_box=request.app.state.secret_box,
        clock=SystemClock(),
    )


def build_issue_invitation(
    request: Request, session: SessionDep, settings: SettingsDep
) -> IssueInvitation:
    return IssueInvitation(
        users=PostgresUserRepository(session),
        invitations=PostgresInvitationRepository(session),
        tokens=request.app.state.tokens,
        audit=request.app.state.audit,
        authz=request.app.state.authz,
        clock=SystemClock(),
        ttl_seconds=settings.invitation_ttl_seconds,
    )


def build_accept_invitation(
    request: Request, session: SessionDep, settings: SettingsDep
) -> AcceptInvitation:
    return AcceptInvitation(
        users=PostgresUserRepository(session),
        invitations=PostgresInvitationRepository(session),
        tokens=request.app.state.tokens,
        totp=request.app.state.totp,
        hasher=request.app.state.hasher,
        policy=request.app.state.password_policy,
        secret_box=request.app.state.secret_box,
        pending=build_pending_enrolment(request, settings),
        sessions=request.app.state.sessions,
        audit=request.app.state.audit,
        clock=SystemClock(),
        issuer=settings.totp_issuer,
    )


def build_pending_enrolment(request: Request, settings: Settings) -> PendingEnrolment:
    return PendingEnrolment(
        request.app.state.cache,
        request.app.state.secret_box,
        ttl_seconds=settings.totp_enrolment_ttl_seconds,
    )


def build_manage_models(
    request: Request, session: SessionDep, settings: SettingsDep
) -> ManageModels:
    return ManageModels(
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        policies=PostgresRoutingPolicyRepository(session),
        runtimes=request.app.state.runtimes,
        budget=MemoryBudgetService(),
        # Its own session factory, so a terminal state write survives the
        # request transaction rolling back when a load or unload raises.
        state_committer=ModelStateCommitter(get_session_factory()),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_download_model(request: Request, session: SessionDep) -> DownloadModel:
    return DownloadModel(
        models=PostgresModelRepository(session),
        runtimes=request.app.state.runtimes,
        jobs=request.app.state.jobs,
        state_committer=ModelStateCommitter(get_session_factory()),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_manage_api_keys(request: Request, session: SessionDep) -> ManageApiKeys:
    return ManageApiKeys(
        keys=PostgresApiKeyRepository(session),
        users=PostgresUserRepository(session),
        usage=PostgresUsageRepository(session),
        service=request.app.state.api_key_service,
        authz=request.app.state.authz,
        audit=request.app.state.audit,
        clock=SystemClock(),
    )


def build_manage_users(request: Request, session: SessionDep) -> ManageUsers:
    return ManageUsers(
        users=PostgresUserRepository(session),
        keys=PostgresApiKeyRepository(session),
        invitations=PostgresInvitationRepository(session),
        sessions=request.app.state.sessions,
        authz=request.app.state.authz,
        audit=request.app.state.audit,
        clock=SystemClock(),
    )


def build_manage_routing_policies(request: Request, session: SessionDep) -> ManageRoutingPolicies:
    return ManageRoutingPolicies(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_read_dashboard(request: Request, session: SessionDep) -> ReadDashboard:
    return ReadDashboard(
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        keys=PostgresApiKeyRepository(session),
        users=PostgresUserRepository(session),
        usage=PostgresUsageRepository(session),
        authz=request.app.state.authz,
        clock=SystemClock(),
    )


def build_manage_own_account(
    request: Request, session: SessionDep, settings: SettingsDep
) -> ManageOwnAccount:
    return ManageOwnAccount(
        users=PostgresUserRepository(session),
        invitations=PostgresInvitationRepository(session),
        tokens=request.app.state.tokens,
        totp=request.app.state.totp,
        hasher=request.app.state.hasher,
        policy=request.app.state.password_policy,
        secret_box=request.app.state.secret_box,
        pending=build_pending_enrolment(request, settings),
        sessions=request.app.state.sessions,
        audit=request.app.state.audit,
        clock=SystemClock(),
        issuer=settings.totp_issuer,
    )
