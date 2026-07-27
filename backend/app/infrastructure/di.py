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
from app.adapters.http.egress_guard import TailnetEgressGuard
from app.adapters.http.node_health import RuntimeNodeHealth
from app.adapters.metrics.prometheus import MeteredUsageRepository
from app.adapters.persistence.model_state import ModelStateCommitter
from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresAuditLogRepository,
    PostgresInvitationRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
    PostgresTenantRepository,
    PostgresUsageRepository,
    PostgresUserRepository,
)
from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.adapters.session.session_store import SessionData, SessionStore
from app.application.use_cases.accept_invitation import AcceptInvitation
from app.application.use_cases.authenticate_local import AuthenticateLocal
from app.application.use_cases.bootstrap_first_admin import BootstrapFirstAdmin
from app.application.use_cases.download_model import DownloadModel
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.manage_api_keys import ManageApiKeys
from app.application.use_cases.manage_models import ManageModels
from app.application.use_cases.manage_nodes import ManageNodes
from app.application.use_cases.manage_own_account import ManageOwnAccount
from app.application.use_cases.manage_routing_policies import ManageRoutingPolicies
from app.application.use_cases.manage_tenants import ManageTenants
from app.application.use_cases.manage_users import ManageUsers
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.application.use_cases.read_audit_log import ReadAuditLog
from app.application.use_cases.read_dashboard import ReadDashboard
from app.application.use_cases.read_usage_analytics import ReadUsageAnalytics
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.entities.actor import Actor
from app.domain.entities.model import RuntimeKind
from app.domain.ports.infrastructure_ports import CachePort
from app.domain.ports.model_runtime_port import ModelRuntimePort
from app.domain.ports.repositories import UsageRepositoryPort
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
        ),
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


# --- identity seam -------------------------------------------------------
#
# `current_actor` and `current_session` live here, not in the identity
# middleware, so that the tenant-scoped repository builders below can depend on
# the actor without a circular import (identity imports di, so di must not import
# identity). The middleware re-exports both and installs the real resolvers via
# `dependency_overrides`; routers keep importing them from the middleware.


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


# --- repositories --------------------------------------------------------
#
# The tenant-scoped repositories come in two forms. The plain getters are
# **unscoped**: they serve the identity resolvers and the gateway's key
# authentication, which resolve a principal (by session id, login, or key handle)
# before any tenant is known, and reading exactly the one row a unique handle
# names is not a cross-tenant enumeration. The `*_scoped` getters and the use-case
# builders below construct repositories bound to the actor's tenant, which is
# where the §7.3 boundary is enforced.


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


def build_route_chat_request(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> RouteChatRequest:
    # Unscoped: RouteChatRequest stamps the record's tenant from the authenticated
    # actor, so the write lands under the key's tenant. Wrapped to emit inference
    # metrics from the same UsageRecord the streaming path already produces, which
    # is what keeps that generator untouched; see adapters/metrics/prometheus.py.
    usage: UsageRepositoryPort = PostgresUsageRepository.unscoped(session)
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        usage = MeteredUsageRepository(usage, metrics)
    return RouteChatRequest(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        usage=usage,
        runtimes=request.app.state.runtimes,
        routing=RoutingService(),
        concurrency=request.app.state.concurrency,
        authz=request.app.state.authz,
        clock=SystemClock(),
        max_tokens_ceiling=settings.max_tokens_ceiling,
        max_context_chars=settings.max_context_length * 4,
        generation_deadline_seconds=settings.generation_deadline_seconds,
        thinking_default=settings.ollama_thinking,
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
        # Unscoped: bootstrap counts every user platform-wide (it is inert once
        # any user exists anywhere) and creates the first admin in the default
        # tenant the account already carries.
        users=PostgresUserRepository.unscoped(session),
        audit=request.app.state.audit,
        authz=request.app.state.authz,
        bootstrap_login=settings.bootstrap_admin_login,
    )


def build_authenticate_local(request: Request, session: SessionDep) -> AuthenticateLocal:
    return AuthenticateLocal(
        # Unscoped: login is globally unique and authentication resolves it
        # before any tenant is known.
        users=PostgresUserRepository.unscoped(session),
        hasher=request.app.state.hasher,
        totp=request.app.state.totp,
        invitations=PostgresInvitationRepository(session),
        tokens=request.app.state.tokens,
        throttle=LoginThrottle(request.app.state.cache),
        secret_box=request.app.state.secret_box,
        clock=SystemClock(),
    )


def build_issue_invitation(
    request: Request, session: SessionDep, settings: SettingsDep, tenant: TenantIdDep
) -> IssueInvitation:
    return IssueInvitation(
        # Scoped: the invited account lands in the inviting admin's tenant, which
        # the scoped repository stamps on write.
        users=PostgresUserRepository(session, tenant),
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
        # Unscoped: the account being completed is identified by the invitation
        # token, not by an authenticated actor, so there is no tenant to scope by.
        users=PostgresUserRepository.unscoped(session),
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


def build_manage_api_keys(
    request: Request, session: SessionDep, tenant: TenantIdDep
) -> ManageApiKeys:
    return ManageApiKeys(
        # Scoped to the caller's tenant: an admin issues, lists, edits and
        # revokes only their own tenant's keys, and a key is owned by a user in
        # that same tenant.
        keys=PostgresApiKeyRepository(session, tenant),
        users=PostgresUserRepository(session, tenant),
        usage=PostgresUsageRepository(session, tenant),
        service=request.app.state.api_key_service,
        authz=request.app.state.authz,
        audit=request.app.state.audit,
        clock=SystemClock(),
    )


def build_manage_users(request: Request, session: SessionDep, tenant: TenantIdDep) -> ManageUsers:
    return ManageUsers(
        users=PostgresUserRepository(session, tenant),
        keys=PostgresApiKeyRepository(session, tenant),
        invitations=PostgresInvitationRepository(session),
        sessions=request.app.state.sessions,
        authz=request.app.state.authz,
        audit=request.app.state.audit,
        clock=SystemClock(),
    )


def build_manage_nodes(request: Request, session: SessionDep) -> ManageNodes:
    """The egress guard and the health probe are both cheap and stateless, so
    they are constructed here rather than held on `app.state`. The probe reads
    the process-wide runtimes so it checks the same adapters inference uses."""
    return ManageNodes(
        nodes=PostgresNodeRepository(session),
        models=PostgresModelRepository(session),
        egress=TailnetEgressGuard(),
        health=RuntimeNodeHealth(request.app.state.runtimes),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_manage_tenants(
    request: Request, session: SessionDep, settings: SettingsDep
) -> ManageTenants:
    """The invitation collaborator uses an *unscoped* user repository, because
    creating a tenant's first admin writes into the new tenant, not the caller's,
    so the tenant must be set explicitly rather than stamped from the actor."""
    invite = IssueInvitation(
        users=PostgresUserRepository.unscoped(session),
        invitations=PostgresInvitationRepository(session),
        tokens=request.app.state.tokens,
        audit=request.app.state.audit,
        authz=request.app.state.authz,
        clock=SystemClock(),
        ttl_seconds=settings.invitation_ttl_seconds,
    )
    return ManageTenants(
        tenants=PostgresTenantRepository(session),
        invite=invite,
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_manage_routing_policies(request: Request, session: SessionDep) -> ManageRoutingPolicies:
    return ManageRoutingPolicies(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_read_dashboard(
    request: Request, session: SessionDep, tenant: TenantIdDep
) -> ReadDashboard:
    return ReadDashboard(
        # Models and nodes are shared infrastructure, so their counts are
        # platform-wide; keys, users and usage are the tenant's own.
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        keys=PostgresApiKeyRepository(session, tenant),
        users=PostgresUserRepository(session, tenant),
        usage=PostgresUsageRepository(session, tenant),
        authz=request.app.state.authz,
        clock=SystemClock(),
    )


def build_read_audit_log(
    request: Request, session: SessionDep, tenant: TenantIdDep
) -> ReadAuditLog:
    return ReadAuditLog(
        # Scoped: the logs view shows only the caller's own tenant's trail.
        entries=PostgresAuditLogRepository(session, tenant),
        authz=request.app.state.authz,
    )


def build_read_usage_analytics(
    request: Request, session: SessionDep, tenant: TenantIdDep
) -> ReadUsageAnalytics:
    return ReadUsageAnalytics(
        # Scoped: a tenant's charts show only its own usage, like the dashboard.
        usage=PostgresUsageRepository(session, tenant),
        authz=request.app.state.authz,
        clock=SystemClock(),
    )


def build_manage_own_account(
    request: Request, session: SessionDep, settings: SettingsDep, tenant: TenantIdDep
) -> ManageOwnAccount:
    return ManageOwnAccount(
        # Scoped to the caller's own tenant; the account being managed is theirs.
        users=PostgresUserRepository(session, tenant),
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
