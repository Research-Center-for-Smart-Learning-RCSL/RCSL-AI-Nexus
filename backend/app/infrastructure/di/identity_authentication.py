"""Dependency providers for identity authentication."""

from __future__ import annotations

from fastapi import Request

from app.adapters.audit.postgres_audit import PostgresAudit
from app.adapters.crypto.argon2_hasher import Argon2Hasher
from app.adapters.crypto.pyotp_totp import PyotpTotp
from app.adapters.crypto.secret_box import FernetSecretBox
from app.adapters.crypto.zxcvbn_policy import ZxcvbnPasswordPolicy
from app.adapters.persistence.repositories import (
    PostgresInvitationRepository,
    PostgresUserRepository,
)
from app.adapters.session.session_store import SessionStore
from app.application.use_cases.accept_invitation import AcceptInvitation
from app.application.use_cases.authenticate_local import AuthenticateLocal
from app.application.use_cases.bootstrap_first_admin import BootstrapFirstAdmin
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.manage_own_account import ManageOwnAccount
from app.application.use_cases.pending_enrolment import PendingEnrolment
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.services.login_throttle import LoginThrottle
from app.domain.services.token_service import TokenService
from app.infrastructure.config import Settings
from app.shared.clock import SystemClock

from .shared import SessionDep, SettingsDep, TenantIdDep


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
        audit=request.app.state.audit,
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
