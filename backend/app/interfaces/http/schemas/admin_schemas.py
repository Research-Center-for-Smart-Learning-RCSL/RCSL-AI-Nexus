"""Request and response shapes for the admin API.

These mirror the zod schemas under frontend/src/features. The frontend parses
every response rather than casting it, so a field renamed here surfaces as a
parse failure on the next call rather than as `undefined` three components
later.

**Nothing here carries a credential outward.** `password_hash` and
`totp_secret` have no representation: the UI learns only whether they are set.
The three values that are returned once and never again — an invitation URL,
a TOTP secret, a set of recovery codes — are marked as such where they appear.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.adapters.authz.role_authorization import ASSIGNABLE_ROLES
from app.application.use_cases.read_audit_log import AuditLogPage
from app.application.use_cases.read_usage_analytics import UsageAnalytics
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.audit import AuditEntry
from app.domain.entities.invitation import Invitation
from app.domain.entities.knowledge import (
    KnowledgeCollection,
    KnowledgeDocument,
    RetrievedPassage,
)
from app.domain.entities.model import Model, RuntimeKind
from app.domain.entities.node import Node
from app.domain.entities.retention import RetentionPolicy
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.tenant import Tenant
from app.domain.entities.user import User
from app.domain.ports.infrastructure_ports import JobStatus


def _as_utc(value: datetime) -> datetime:
    """Read a naive value as UTC rather than rejecting it.

    The expiry field is rendered as `<input type="date">`, which can only
    produce `YYYY-MM-DD`. Pydantic parses that into a **naive** datetime, and
    comparing one to `datetime.now(UTC)` raises `TypeError` — not a
    `DomainError`, so it escaped the handler as a bare 500 and no API key
    could ever be issued from the UI.

    Coercing rather than rejecting, because a date with no zone is what the
    form is able to send and "midnight UTC on that day" is what it means.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
"""Every datetime crossing this boundary is timezone-aware, so no comparison
downstream has to wonder."""


def _human_role(role: Role) -> Role:
    """Refuses the SERVICE role on a human account.

    `SERVICE` exists for API keys. `ASSIGNABLE_ROLES` is the list a person may
    hold, and it is every role except that one — accepting it here would create
    an account whose permissions were designed for a machine credential.

    The message enumerates from that list rather than naming roles inline. It
    said "role must be 'admin' or 'user'" for a day after there were six, which
    is a 422 that tells the caller two of the answers it could have given.
    """
    if role is Role.SERVICE:
        allowed = ", ".join(repr(r.value) for r in ASSIGNABLE_ROLES)
        raise ValueError(f"role must be one of {allowed}")
    return role


HumanRole = Annotated[Role, AfterValidator(_human_role)]


class MeResponse(BaseModel):
    id: str
    auth_mode: str
    login: str
    display_name: str
    role: str
    scopes: list[str] = Field(default_factory=list)
    """What this caller may do, resolved from the role by `AuthorizationPort`.

    Sent so the UI can gate on the permission rather than on the role name. It
    branched on `isAdmin` in forty-five places, which is a question with two
    answers on a platform that now has six roles: `operator` would have been
    shown a read-only fleet it can in fact write, and `auditor` an Invite
    button the server refuses. Not a secret — it is derived from a hardcoded
    table and every entry is documented in security.md §5.2 — and not a
    control either: the server checks the same scopes on every request, and
    §5.2's "UI-level role gating is a usability affordance only" still holds."""

    session_expires_at: datetime | None = None
    """None on the tailnet entrance, which has no session at all."""


class RoleResponse(BaseModel):
    """One row of the role catalogue.

    Carries the scope list rather than prose. The wording that explains a role
    to a person is copy and lives in the UI; the list of what it actually
    grants is derived from the authorization table, so the two cannot disagree
    about the part that matters."""

    role: str
    scopes: list[str]


class UserResponse(BaseModel):
    id: str
    login: str
    display_name: str
    tailscale_login: str | None
    has_local_credentials: bool
    has_totp: bool
    role: str
    debug_logging_until: datetime | None
    created_at: datetime | None

    @classmethod
    def of(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            login=user.login,
            display_name=user.display_name,
            tailscale_login=user.tailscale_login,
            # Derived, never the hash itself.
            has_local_credentials=user.password_hash is not None,
            has_totp=user.totp_secret is not None,
            role=user.role.value,
            debug_logging_until=user.debug_logging_until,
            created_at=user.created_at,
        )


class CreateUserRequest(BaseModel):
    login: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    role: HumanRole


class InvitationResponse(BaseModel):
    id: str
    user_id: str
    url: str | None = None
    """The full single-use link. Present only in the response that issued it;
    only the token's hash is stored, so it cannot be produced again."""

    expires_at: datetime
    consumed_at: datetime | None = None

    @classmethod
    def of(cls, invitation: Invitation, *, url: str | None = None) -> InvitationResponse:
        return cls(
            id=invitation.id,
            user_id=invitation.user_id,
            url=url,
            expires_at=invitation.expires_at,
            consumed_at=invitation.consumed_at,
        )


class CreateUserResponse(BaseModel):
    user: UserResponse
    invitation: InvitationResponse


# --- tenants -------------------------------------------------------------


class TenantResponse(BaseModel):
    id: str
    name: str
    created_at: datetime | None

    @classmethod
    def of(cls, tenant: Tenant) -> TenantResponse:
        return cls(id=tenant.id, name=tenant.name, created_at=tenant.created_at)


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    first_admin_login: EmailStr
    """A tenant with no administrator cannot be populated, so creating one mints
    its first admin's invitation. The login is globally unique, like every other."""

    first_admin_display_name: str = Field(min_length=1, max_length=120)


class CreateTenantResponse(BaseModel):
    tenant: TenantResponse
    invitation: InvitationResponse
    """The first administrator's onboarding link, present here and nowhere else."""


# --- authentication ------------------------------------------------------


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    """Bounded so an unauthenticated caller cannot make the server hash a
    megabyte. The strength check has its own, higher, ceiling."""


class LoginChallengeResponse(BaseModel):
    challenge: str
    """Opaque handle for the second step. Not a session, and carries no
    privilege: it names a user whose password was verified, nothing more."""

    next: str = "totp"


class TotpLoginRequest(BaseModel):
    challenge: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=8)


class RecoveryCodeLoginRequest(BaseModel):
    challenge: str = Field(min_length=1, max_length=256)
    recovery_code: str = Field(min_length=1, max_length=64)


class EnrolmentResponse(BaseModel):
    provisioning_uri: str
    secret: str
    """Shown once, during enrolment, for the case where no camera is
    available. Never returned afterwards by any endpoint."""

    login: str


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=512)
    totp_code: str = Field(min_length=6, max_length=8)


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
    """The only copy that will ever exist."""


class ResetTargetResponse(BaseModel):
    login: str


class ConsumeResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=512)


class BeginTotpRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    """Re-enrolment replaces a bearer credential, so it proves the current
    password first, exactly as a password change does."""


class ConfirmTotpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: HumanRole | None = None
    disabled: bool | None = None


# --- models and nodes ----------------------------------------------------


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


ALIAS_PATTERN = r"^[a-z0-9-]+$"
REF_PATTERN = r"^[A-Za-z0-9._:/-]+$"
"""Mirrors the frontend. The authoritative check is `validate_model_ref` in
the runtime adapter; this one keeps an obviously wrong value from reaching the
use case at all."""


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


# --- API keys ------------------------------------------------------------


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    scopes: list[str]
    rate_limit_rpm: int
    quota_tokens_per_day: int
    allowed_cidrs: list[str]
    expires_at: datetime
    owner_id: str
    owner_display: str | None
    revoked_at: datetime | None
    created_at: datetime | None
    last_used_at: datetime | None
    """Derived from `usage_records`, not stored on the key. Maintaining a
    column would put a write to `api_keys` on the gateway's hot path, which
    the account split exists to prevent."""

    @classmethod
    def of(
        cls,
        key: ApiKey,
        *,
        owner_display: str | None = None,
        last_used_at: datetime | None = None,
    ) -> ApiKeyResponse:
        return cls(
            # The digest is absent, and there is no field for it. A response
            # model that cannot express the secret cannot leak it by accident.
            key_id=key.key_id,
            name=key.name,
            scopes=sorted(key.scopes),
            rate_limit_rpm=key.rate_limit_rpm,
            # The frontend treats this as a plain number; zero reads as "no
            # quota", which is what None means here.
            quota_tokens_per_day=key.quota_tokens_per_day or 0,
            allowed_cidrs=[str(n) for n in key.allowed_cidrs],
            expires_at=key.expires_at,
            owner_id=key.owner_id,
            owner_display=owner_display,
            revoked_at=key.revoked_at,
            created_at=key.created_at,
            last_used_at=last_used_at,
        )


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    owner_id: str = Field(min_length=1, max_length=36)
    scopes: list[str] = Field(min_length=1)
    rate_limit_rpm: int = Field(ge=1, le=100_000)
    """`ge=1`, not `ge=0`. The gateway reads `rate_limit_rpm <= 0` as **no
    limit** (`middleware/api_key_auth.py`), so zero was a way to issue an
    unmetered key through a form that reads as if it were tightening one. The
    frontend already declares this positive; the backend was the looser of the
    two."""

    quota_tokens_per_day: int = Field(ge=1)
    """Same reasoning, plus the two verbs disagreed: on create the router
    mapped `0` to `None` (no quota at all), while on update `0` was stored
    literally and refused every request forever. Zero is now inexpressible."""
    allowed_cidrs: list[str] = Field(default_factory=list)
    expires_at: UtcDatetime
    """Mandatory, with no "never" option, so that rotation is forced rather
    than encouraged."""


class UpdateApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    scopes: list[str] | None = Field(default=None, min_length=1)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100_000)
    quota_tokens_per_day: int | None = Field(default=None, ge=1)
    allowed_cidrs: list[str] | None = None
    expires_at: UtcDatetime | None = None


class IssuedApiKeyResponse(BaseModel):
    key: ApiKeyResponse
    plaintext: str
    """Present in this response and in no other, ever."""


# --- gateway information -------------------------------------------------


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


# --- routing policies ----------------------------------------------------


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

    @classmethod
    def of(cls, policy: RoutingPolicy) -> RoutingPolicyResponse:
        return cls(
            capability=policy.capability,
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


# --- dashboard -----------------------------------------------------------


class DashboardResponse(BaseModel):
    models_total: int
    models_loaded: int
    nodes_online: int
    nodes_total: int
    api_keys_active: int
    users_total: int
    requests_last_24h: int
    tokens_last_24h: int


# --- logs ----------------------------------------------------------------


class AuditEntryResponse(BaseModel):
    id: str
    actor_id: str
    actor_display: str
    actor_source: str
    action: str
    target: str | None
    outcome: str
    detail: dict[str, str]
    at: datetime

    @classmethod
    def of(cls, entry: AuditEntry) -> AuditEntryResponse:
        return cls(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_display=entry.actor_display,
            actor_source=entry.actor_source,
            action=entry.action,
            target=entry.target,
            outcome=entry.outcome,
            detail=entry.detail,
            at=entry.at,
        )


class AuditLogResponse(BaseModel):
    entries: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, page: AuditLogPage) -> AuditLogResponse:
        return cls(
            entries=[AuditEntryResponse.of(e) for e in page.entries],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


# --- usage analytics -----------------------------------------------------


class UsagePointResponse(BaseModel):
    t: datetime
    requests: int
    tokens: int


class CapabilitySeriesResponse(BaseModel):
    capability: str
    points: list[UsagePointResponse]


class UsageAnalyticsResponse(BaseModel):
    bucket: str
    since: datetime
    until: datetime
    totals: list[UsagePointResponse]
    by_capability: list[CapabilitySeriesResponse]

    @classmethod
    def of(cls, analytics: UsageAnalytics) -> UsageAnalyticsResponse:
        return cls(
            bucket=analytics.bucket,
            since=analytics.since,
            until=analytics.until,
            totals=[
                UsagePointResponse(t=p.at, requests=p.requests, tokens=p.tokens)
                for p in analytics.totals
            ],
            by_capability=[
                CapabilitySeriesResponse(
                    capability=s.capability,
                    points=[
                        UsagePointResponse(t=p.at, requests=p.requests, tokens=p.tokens)
                        for p in s.points
                    ],
                )
                for s in analytics.by_capability
            ],
        )


# --- Knowledge base ------------------------------------------------------


class KnowledgeCollectionResponse(BaseModel):
    id: str
    name: str
    description: str
    document_count: int
    created_at: datetime | None

    @classmethod
    def of(cls, collection: KnowledgeCollection) -> KnowledgeCollectionResponse:
        return cls(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            document_count=collection.document_count,
            created_at=collection.created_at,
        )


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)


class KnowledgeDocumentResponse(BaseModel):
    id: str
    collection_id: str
    filename: str
    media_type: str
    size_bytes: int
    status: str
    chunk_count: int
    error: str | None
    uploaded_by: str
    uploaded_at: datetime | None

    @classmethod
    def of(cls, document: KnowledgeDocument) -> KnowledgeDocumentResponse:
        return cls(
            id=document.id,
            collection_id=document.collection_id,
            filename=document.filename,
            media_type=document.media_type,
            size_bytes=document.size_bytes,
            status=document.status.value,
            chunk_count=document.chunk_count,
            # The parser's failure class, not its message: a parser message can
            # quote document bytes. See application/use_cases/ingest_document.py.
            error=document.error,
            uploaded_by=document.uploaded_by,
            uploaded_at=document.uploaded_at,
        )


class KnowledgeDocumentPageResponse(BaseModel):
    """Server-paged like the audit log, for the same reason: the table only
    grows, and an unbounded read is a memory lever."""

    documents: list[KnowledgeDocumentResponse]
    total: int
    limit: int
    offset: int


class IngestionJobResponse(BaseModel):
    """Deliberately not `DownloadJobResponse`, whose `model_id` field would name
    a document here. Same shape, honest field names."""

    job_id: str
    document_id: str | None
    """`JobStatus.target` is optional in general; every ingestion job sets it,
    so this is None only for a cache entry written by something else."""

    state: str
    progress: float | None
    message: str | None

    @classmethod
    def of(cls, status: JobStatus) -> IngestionJobResponse:
        return cls(
            job_id=status.job_id,
            document_id=status.target,
            state=status.state,
            progress=status.progress,
            message=status.message,
        )


class DocumentTextResponse(BaseModel):
    """The extracted text of one document, for the preview dialog.

    `truncated` is carried rather than left for the client to infer from the
    length, because the bound is the server's and a client comparing against a
    constant of its own would disagree the first time either changed.
    """

    document_id: str
    text: str
    truncated: bool


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    """Bounded here as well as in the use case: each passage becomes prompt
    context on the chat path, and context cost grows faster than linearly."""


class RetrievedPassageResponse(BaseModel):
    """A passage from a document.

    `text` is **untrusted document content**. Anything rendering it must treat
    it as data: the frontend sanitises markdown with raw HTML disabled
    (frontend.md 7), and prompt assembly marks it as data rather than
    instructions (security.md 7.3).
    """

    document_id: str
    collection_id: str
    index: int
    text: str
    score: float

    @classmethod
    def of(cls, passage: RetrievedPassage) -> RetrievedPassageResponse:
        return cls(
            document_id=passage.document_id,
            collection_id=passage.collection_id,
            index=passage.index,
            text=passage.text,
            score=passage.score,
        )


class KnowledgeSearchResponse(BaseModel):
    passages: list[RetrievedPassageResponse]


# --- Retention -----------------------------------------------------------


class RetentionPolicyResponse(BaseModel):
    dataset: str
    days: int
    updated_at: datetime | None
    updated_by: str | None
    """Null while the dataset is still on the default nobody has changed, which
    the screen shows as "default" rather than as an empty author."""

    @classmethod
    def of(cls, policy: RetentionPolicy) -> RetentionPolicyResponse:
        return cls(
            dataset=policy.dataset.value,
            days=policy.days,
            updated_at=policy.updated_at,
            updated_by=policy.updated_by,
        )


class RetentionPreviewResponse(BaseModel):
    dataset: str
    days: int
    affected: int


class PurgeOutcomeResponse(BaseModel):
    dataset: str
    cutoff: datetime
    deleted: int


class SetRetentionPolicyRequest(BaseModel):
    days: int = Field(ge=1)
    """`ge=1` only keeps the field a positive number; the real floor is
    `MINIMUM_RETENTION_DAYS` and is enforced in the use case, so a caller that
    never touches this schema meets the same rule."""
