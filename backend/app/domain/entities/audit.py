"""A recorded action, and the catalogue of actions that may be recorded.

The write side is `AuditPort` / `PostgresAudit`, which commits each row in its
own transaction so a failed request still leaves its trail. `AuditEntry` is the
read side: a normal tenant-scoped query over the same append-only table, for the
logs view. Kept separate from the write path because reading is an ordinary
request-session query and must not borrow the writer's independent-transaction
machinery.

`AuditAction` is what both sides name. It is here rather than beside either one
because a name written by a use case, stored by the adapter and offered as a
filter on the logs screen has to be the same name in all three places, and the
three had nothing joining them: the action was a bare string literal at every
`record` call, and the screen's suggestion list was a hand-kept copy that had
drifted by eight names before 2026-08-08 (PROGRESS.md that day). Every one of
those was an action an operator could only filter for by already knowing its
exact spelling, which is the failure that list exists to remove.

`AuditPort.record` takes this type, so an action that is not in this enum does
not type-check, and `scripts/emit_audit_actions.py` generates the screen's list
from it. Adding an action is one edit here; forgetting to propagate it is no
longer possible in either direction.

The events themselves are specified in docs/architecture/security.md section 12
-- this enum is the implementation of that list, not a second opinion about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.entities.tenant import DEFAULT_TENANT_ID


class AuditAction(StrEnum):
    """Every action name the platform writes to the audit log.

    A `StrEnum` rather than a plain constant set: the value has to reach a
    `String` column and a JSON response as its own text, while the member is
    what call sites and tests name.
    """

    API_KEY_ISSUED = "api_key.issued"
    API_KEY_UPDATED = "api_key.updated"
    API_KEY_REVOKED = "api_key.revoked"
    API_KEY_DEBUG_WINDOW_SET = "api_key.debug_window_set"

    AUTHZ_DENIED = "authz.denied"
    """Written by the shared exception handler rather than by a use case, so a
    refusal raised without consulting `AuthorizationPort` is still recorded."""

    BOOTSTRAP_FIRST_ADMIN = "bootstrap.first_admin"

    KNOWLEDGE_COLLECTION_CREATED = "knowledge.collection_created"
    KNOWLEDGE_COLLECTION_DELETED = "knowledge.collection_deleted"
    KNOWLEDGE_DOCUMENT_UPLOADED = "knowledge.document_uploaded"
    KNOWLEDGE_DOCUMENT_DELETED = "knowledge.document_deleted"

    MODEL_REGISTERED = "model.registered"
    MODEL_UPDATED = "model.updated"
    MODEL_DELETED = "model.deleted"
    MODEL_DOWNLOAD_STARTED = "model.download_started"
    MODEL_LOADED = "model.loaded"
    MODEL_UNLOADED = "model.unloaded"

    NODE_REGISTERED = "node.registered"
    NODE_UPDATED = "node.updated"
    NODE_REMOVED = "node.removed"

    PROMPT_LOG_READ = "prompt_log.read"
    """Reading one transcript. Listing is deliberately not audited: the list
    carries no message content, and an event there would fire on every page
    refresh."""

    PROMPT_TEMPLATE_CREATED = "prompt_template.created"
    PROMPT_TEMPLATE_UPDATED = "prompt_template.updated"
    PROMPT_TEMPLATE_DELETED = "prompt_template.deleted"

    RETENTION_POLICY_SET = "retention.policy_set"
    RETENTION_PURGED = "retention.purged"

    ROUTING_POLICY_SAVED = "routing_policy.saved"
    ROUTING_POLICY_DELETED = "routing_policy.deleted"

    TENANT_CREATED = "tenant.created"

    USER_INVITED = "user.invited"
    USER_INVITATION_REISSUED = "user.invitation_reissued"
    USER_INVITATION_ACCEPTED = "user.invitation_accepted"
    # S105 reads a member whose name contains PASSWORD as a hardcoded credential.
    # These are event names written to an append-only log; section 12 forbids a
    # credential anywhere in a row, which is the opposite of what it suspects.
    USER_PASSWORD_RESET_ISSUED = "user.password_reset_issued"  # noqa: S105
    USER_PASSWORD_RESET_CONSUMED = "user.password_reset_consumed"  # noqa: S105
    USER_PASSWORD_CHANGED = "user.password_changed"  # noqa: S105
    USER_PASSWORD_VERIFIED = "user.password_verified"  # noqa: S105
    USER_TOTP_ENROLLED = "user.totp_enrolled"
    USER_TOTP_REENROLLED = "user.totp_reenrolled"
    USER_SIGNED_IN = "user.signed_in"
    USER_SIGNED_OUT = "user.signed_out"
    USER_SIGN_IN_FAILED = "user.sign_in_failed"
    USER_SIGN_IN_THROTTLED = "user.sign_in_throttled"
    USER_RECOVERY_CODE_USED = "user.recovery_code_used"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_UPDATED = "user.updated"
    USER_ENABLED = "user.enabled"
    USER_DISABLED = "user.disabled"
    USER_DELETED = "user.deleted"
    USER_DEBUG_WINDOW_SET = "user.debug_window_set"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: str
    actor_id: str
    actor_display: str
    """Login or key handle, never a secret; safe to render."""

    actor_source: str
    action: str
    target: str | None
    outcome: str
    detail: dict[str, str]
    """Identifiers and reasons only. Section 12 forbids a credential, token,
    prompt, or completion here, so the read path can surface it verbatim."""

    at: datetime
    tenant_id: str = DEFAULT_TENANT_ID
