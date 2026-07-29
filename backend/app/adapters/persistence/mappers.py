"""Translation between ORM rows and domain entities.

The two are separate types on purpose (see sqlalchemy_models.py), so the
conversion has to live somewhere explicit rather than being implied by shared
attribute names. Keeping it in one module means a schema change surfaces here
as a compile-time or test failure instead of leaking into use cases.
"""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Any

from app.adapters.persistence.sqlalchemy_models import (
    ApiKeyRow,
    AuditLogRow,
    InvitationRow,
    KnowledgeCollectionRow,
    KnowledgeDocumentRow,
    ModelRow,
    NodeRow,
    RecoveryCodeRow,
    RoutingPolicyRow,
    TenantRow,
    UsageRecordRow,
    UserRow,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.audit import AuditEntry
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import (
    Requirement,
    RoutingCandidate,
    RoutingPolicy,
)
from app.domain.entities.tenant import Tenant
from app.domain.entities.usage import UsageRecord
from app.domain.entities.user import User

# --- Tenant --------------------------------------------------------------


def tenant_to_domain(row: TenantRow) -> Tenant:
    return Tenant(id=row.id, name=row.name, created_at=row.created_at)


def tenant_to_row(tenant: Tenant) -> TenantRow:
    row = TenantRow(id=tenant.id, name=tenant.name)
    if tenant.created_at is not None:
        row.created_at = tenant.created_at
    return row


# --- Node ----------------------------------------------------------------


def node_to_domain(row: NodeRow) -> Node:
    return Node(
        id=row.id,
        name=row.name,
        address=row.address,
        status=NodeStatus(row.status),
        total_memory_gb=row.total_memory_gb,
        runtimes=frozenset(RuntimeKind(r) for r in row.runtimes or []),
    )


def node_to_row(node: Node) -> NodeRow:
    return NodeRow(
        id=node.id,
        name=node.name,
        address=node.address,
        status=node.status.value,
        total_memory_gb=node.total_memory_gb,
        runtimes=sorted(r.value for r in node.runtimes),
    )


# --- Model ---------------------------------------------------------------


def model_to_domain(row: ModelRow) -> Model:
    return Model(
        id=row.id,
        alias=row.alias,
        ref=row.ref,
        runtime=RuntimeKind(row.runtime),
        node_id=row.node_id,
        state=ModelState(row.state),
        capabilities=frozenset(row.capabilities or []),
        resource_profile=ResourceProfile(
            memory_gb=row.memory_gb,
            context_length=row.context_length,
        ),
    )


def model_to_row(model: Model) -> ModelRow:
    return ModelRow(
        id=model.id,
        alias=model.alias,
        ref=model.ref,
        runtime=model.runtime.value,
        node_id=model.node_id,
        state=model.state.value,
        capabilities=sorted(model.capabilities),
        memory_gb=model.resource_profile.memory_gb,
        context_length=model.resource_profile.context_length,
    )


# --- Routing policy ------------------------------------------------------
#
# Requirements are persisted as a structured document, never as an expression
# string. Deserialisation below only ever reads known keys into known fields,
# so a hand-edited row cannot introduce a new kind of condition, let alone
# anything evaluable. See docs/ARCHITECTURE.md section 2.4.


def _requirement_to_json(req: Requirement) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if req.node_status:
        payload["node_status"] = sorted(s.value for s in req.node_status)
    if req.model_state:
        payload["model_state"] = sorted(s.value for s in req.model_state)
    if req.min_free_memory_gb is not None:
        payload["min_free_memory_gb"] = req.min_free_memory_gb
    return payload


def _requirement_from_json(payload: dict[str, Any] | None) -> Requirement:
    payload = payload or {}
    return Requirement(
        node_status=frozenset(NodeStatus(s) for s in payload.get("node_status", [])),
        model_state=frozenset(ModelState(s) for s in payload.get("model_state", [])),
        min_free_memory_gb=payload.get("min_free_memory_gb"),
    )


def routing_policy_to_domain(row: RoutingPolicyRow) -> RoutingPolicy:
    candidates = tuple(
        RoutingCandidate(
            model_alias=entry["model_alias"],
            priority=int(entry.get("priority", 0)),
            require=_requirement_from_json(entry.get("require")),
        )
        for entry in row.candidates or []
    )
    return RoutingPolicy(capability=row.capability, candidates=candidates)


def routing_policy_to_row(policy: RoutingPolicy) -> RoutingPolicyRow:
    return RoutingPolicyRow(
        capability=policy.capability,
        candidates=[
            {
                "model_alias": c.model_alias,
                "priority": c.priority,
                "require": _requirement_to_json(c.require),
            }
            for c in policy.candidates
        ],
    )


# --- API key -------------------------------------------------------------


def api_key_to_domain(row: ApiKeyRow) -> ApiKey:
    networks: list[IPv4Network | IPv6Network] = [
        ip_network(entry) for entry in row.allowed_cidrs or []
    ]
    return ApiKey(
        id=row.id,
        tenant_id=row.tenant_id,
        key_id=row.key_id,
        digest=row.digest,
        name=row.name,
        owner_id=row.owner_id,
        scopes=frozenset(row.scopes or []),
        allowed_cidrs=tuple(networks),
        rate_limit_rpm=row.rate_limit_rpm,
        quota_tokens_per_day=row.quota_tokens_per_day,
        expires_at=row.expires_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        debug_logging_until=row.debug_logging_until,
    )


def api_key_to_row(key: ApiKey) -> ApiKeyRow:
    row = ApiKeyRow(
        id=key.id,
        tenant_id=key.tenant_id,
        key_id=key.key_id,
        digest=key.digest,
        name=key.name,
        owner_id=key.owner_id,
        scopes=sorted(key.scopes),
        allowed_cidrs=[str(n) for n in key.allowed_cidrs],
        rate_limit_rpm=key.rate_limit_rpm,
        quota_tokens_per_day=key.quota_tokens_per_day,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        debug_logging_until=key.debug_logging_until,
    )
    if key.created_at is not None:
        # Left unset when the entity has never been persisted, so the column's
        # server default applies rather than a value computed in the process
        # that happens to be issuing the key.
        row.created_at = key.created_at
    return row


# --- User ----------------------------------------------------------------


def user_to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        tenant_id=row.tenant_id,
        login=row.login,
        display_name=row.display_name,
        role=Role(row.role),
        tailscale_login=row.tailscale_login,
        password_hash=row.password_hash,
        totp_secret=row.totp_secret,
        totp_last_counter=row.totp_last_counter,
        created_at=row.created_at,
        debug_logging_until=row.debug_logging_until,
        disabled_at=row.disabled_at,
    )


def user_to_row_values(user: User) -> dict[str, object]:
    """Column values as a mapping, for statements that cannot take an ORM
    object: `insert_if_absent` builds an `ON CONFLICT` statement. Kept as the
    single definition of the column list so a new field cannot be added to one
    path and forgotten on the other."""
    values: dict[str, object] = {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "login": user.login,
        "display_name": user.display_name,
        "role": user.role.value,
        "tailscale_login": user.tailscale_login,
        "password_hash": user.password_hash,
        "totp_secret": user.totp_secret,
        "totp_last_counter": user.totp_last_counter,
        "debug_logging_until": user.debug_logging_until,
        "disabled_at": user.disabled_at,
    }
    if user.created_at is not None:
        # Omitted rather than passed as None when the entity has never been
        # persisted, so the column's server default applies. Passing None would
        # violate NOT NULL, and passing a value computed here would let a
        # client's clock decide when a row was created.
        values["created_at"] = user.created_at
    return values


def user_to_row(user: User) -> UserRow:
    return UserRow(**user_to_row_values(user))


# --- Invitation ----------------------------------------------------------


def invitation_to_domain(row: InvitationRow) -> Invitation:
    return Invitation(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        purpose=InvitationPurpose(row.purpose),
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
    )


def invitation_to_row(invitation: Invitation) -> InvitationRow:
    return InvitationRow(
        id=invitation.id,
        user_id=invitation.user_id,
        token_hash=invitation.token_hash,
        purpose=invitation.purpose.value,
        expires_at=invitation.expires_at,
        consumed_at=invitation.consumed_at,
    )


def recovery_code_to_domain(row: RecoveryCodeRow) -> RecoveryCode:
    return RecoveryCode(
        id=row.id, user_id=row.user_id, code_hash=row.code_hash, used_at=row.used_at
    )


def recovery_code_to_row(code: RecoveryCode) -> RecoveryCodeRow:
    return RecoveryCodeRow(
        id=code.id, user_id=code.user_id, code_hash=code.code_hash, used_at=code.used_at
    )


# --- Usage ---------------------------------------------------------------


def audit_row_to_domain(row: AuditLogRow) -> AuditEntry:
    # detail is JSON, so its values arrive as Any; coerce to str because the
    # entity and the response both promise str, and the writer only ever stores
    # strings. See adapters/audit/postgres_audit.py.
    return AuditEntry(
        id=row.id,
        actor_id=row.actor_id,
        actor_display=row.actor_display,
        actor_source=row.actor_source,
        action=row.action,
        target=row.target,
        outcome=row.outcome,
        detail={k: str(v) for k, v in (row.detail or {}).items()},
        at=row.at,
        tenant_id=row.tenant_id,
    )


# --- Knowledge base ------------------------------------------------------


def collection_to_domain(
    row: KnowledgeCollectionRow, document_count: int = 0
) -> KnowledgeCollection:
    """`document_count` is passed in rather than read off the row: it is an
    aggregate the repository computes, not a stored column that could drift."""
    return KnowledgeCollection(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        document_count=document_count,
        created_at=row.created_at,
    )


def collection_to_row(collection: KnowledgeCollection) -> KnowledgeCollectionRow:
    return KnowledgeCollectionRow(
        id=collection.id,
        tenant_id=collection.tenant_id,
        name=collection.name,
        description=collection.description,
    )


def document_to_domain(row: KnowledgeDocumentRow) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=row.id,
        tenant_id=row.tenant_id,
        collection_id=row.collection_id,
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        status=DocumentStatus(row.status),
        chunk_count=row.chunk_count,
        error=row.error,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
    )


def document_to_row(document: KnowledgeDocument) -> KnowledgeDocumentRow:
    return KnowledgeDocumentRow(
        id=document.id,
        tenant_id=document.tenant_id,
        collection_id=document.collection_id,
        filename=document.filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        status=document.status.value,
        chunk_count=document.chunk_count,
        error=document.error,
        uploaded_by=document.uploaded_by,
    )


# --- Usage ---------------------------------------------------------------


def usage_to_row(usage: UsageRecord) -> UsageRecordRow:
    return UsageRecordRow(
        id=usage.id,
        tenant_id=usage.tenant_id,
        actor_id=usage.actor_id,
        api_key_id=usage.api_key_id,
        capability=usage.capability,
        model_alias=usage.model_alias,
        tokens=usage.tokens,
        latency_ms=usage.latency_ms,
        completed=usage.completed,
        at=usage.at,
    )
