"""Dependency providers for admin observability."""

from __future__ import annotations

from fastapi import Request

from app.adapters.http.egress_guard import TailnetEgressGuard
from app.adapters.http.host_metrics import HttpHostStatus
from app.adapters.http.node_health import RuntimeNodeHealth
from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresAuditLogRepository,
    PostgresEvaluationRepository,
    PostgresInvitationRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresPromptLogRepository,
    PostgresRecordPurge,
    PostgresRefusalRepository,
    PostgresRetentionPolicyRepository,
    PostgresTenantRepository,
    PostgresUsageRepository,
    PostgresUserRepository,
)
from app.adapters.persistence.sqlalchemy_models import (
    AuditLogRow,
    PromptLogRow,
    RefusalRow,
    UsageRecordRow,
)
from app.application.use_cases.issue_invitation import IssueInvitation
from app.application.use_cases.manage_api_keys import ManageApiKeys
from app.application.use_cases.manage_evaluations import ManageEvaluations
from app.application.use_cases.manage_nodes import ManageNodes
from app.application.use_cases.manage_retention import ManageRetention
from app.application.use_cases.manage_tenants import ManageTenants
from app.application.use_cases.manage_users import ManageUsers
from app.application.use_cases.read_audit_log import ReadAuditLog
from app.application.use_cases.read_dashboard import ReadDashboard
from app.application.use_cases.read_host_status import ReadHostStatus
from app.application.use_cases.read_prompt_logs import ReadPromptLogs
from app.application.use_cases.read_refusals import ReadRefusals
from app.application.use_cases.read_usage_analytics import ReadUsageAnalytics
from app.domain.entities.retention import RetentionDataset
from app.shared.clock import SystemClock

from .identity_authentication import get_audit
from .shared import SessionDep, SettingsDep, TenantIdDep


def build_manage_api_keys(
    request: Request, session: SessionDep, tenant: TenantIdDep, settings: SettingsDep
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
        # Passed rather than left to the use case's own default. `Settings`
        # carried this and `.env.example` documented it, but nothing read
        # either: the use case defaulted to the same 365, so the two agreed by
        # coincidence and setting `API_KEY_MAX_LIFETIME_DAYS=90` changed
        # nothing at all. Wired here because the assistant now has to quote the
        # limit, and a second reader of a number that was never authoritative
        # is how it would start being quoted wrongly.
        max_lifetime_days=settings.api_key_max_lifetime_days,
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


def build_read_prompt_logs(
    request: Request, session: SessionDep, tenant: TenantIdDep
) -> ReadPromptLogs:
    """Scoped, unlike the writer above.

    `build_route_chat_request` constructs this repository *unscoped*, because
    the write stamps the tenant from the authenticated actor and the gateway
    has no tenant of its own. The read must not: a transcript is the most
    sensitive row in the schema, so it gets the boundary the audit log gets and
    the scope comes from the wiring rather than from anything a caller sends.
    """
    return ReadPromptLogs(
        transcripts=PostgresPromptLogRepository(session, tenant),
        authz=request.app.state.authz,
        audit=get_audit(request),
    )


def build_read_refusals(request: Request, session: SessionDep, tenant: TenantIdDep) -> ReadRefusals:
    """Tenant-scoped like every other read, and narrowed further inside.

    The tenant comes from the wiring; the narrowing to one account, for a reader
    without `refusal:read_all`, comes from the use case. Two boundaries rather
    than one because they answer different questions — which installation's rows
    exist, and whose rows this person may see — and collapsing them would put
    the second one in a repository that has no idea who is asking.
    """
    return ReadRefusals(
        refusals=PostgresRefusalRepository(session, tenant),
        authz=request.app.state.authz,
        audit=get_audit(request),
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


def build_manage_retention(request: Request, session: SessionDep) -> ManageRetention:
    """No `TenantIdDep`, unlike every neighbour in this file.

    Retention is platform-wide and its scope is admin-only, so the repositories
    here are deliberately unscoped: a purge confined to the caller's tenant
    would delete less than the number it reported, and a policy that differed
    per tenant is not the thing the administrator was offered.
    """
    return ManageRetention(
        policies=PostgresRetentionPolicyRepository(session),
        purges={
            RetentionDataset.AUDIT_LOG: PostgresRecordPurge(session, AuditLogRow),
            RetentionDataset.USAGE_RECORDS: PostgresRecordPurge(session, UsageRecordRow),
            RetentionDataset.PROMPT_LOGS: PostgresRecordPurge(session, PromptLogRow),
            RetentionDataset.REFUSALS: PostgresRecordPurge(session, RefusalRow),
        },
        authz=request.app.state.authz,
        audit=get_audit(request),
        clock=SystemClock(),
    )


def build_manage_evaluations(request: Request, session: SessionDep) -> ManageEvaluations:
    """No `TenantIdDep`, like `build_manage_retention` above and unlike most of
    this file.

    An evaluation describes the fleet rather than a tenant's content -- the same
    reasoning that keeps models and nodes unscoped. Scoping it would mean every
    tenant importing the same measurement of the same hardware.
    """
    return ManageEvaluations(
        evaluations=PostgresEvaluationRepository(session),
        authz=request.app.state.authz,
        audit=get_audit(request),
        clock=SystemClock(),
    )


def build_read_host_status(request: Request, settings: SettingsDep) -> ReadHostStatus:
    return ReadHostStatus(
        host=HttpHostStatus(settings.host_metrics_url),
        authz=request.app.state.authz,
    )
