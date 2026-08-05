"""Domain error hierarchy.

Every domain error carries a stable machine `code` and a `public_message`
that is safe to return to a caller. A single exception handler in
interfaces/http/errors.py performs the HTTP mapping, so routers do not write
their own try/except blocks and error bodies cannot accidentally leak
internal model names, node addresses, or stack traces.
See docs/architecture/backend.md section 5.
"""

from __future__ import annotations


class DomainError(Exception):
    code: str = "internal_error"
    public_message: str = "An internal error occurred."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.public_message)
        self.detail = detail
        """Operator-facing context. Written to the application log with the
        request id; never included in a response body."""


# --- Models and routing --------------------------------------------------


class ModelNotFoundError(DomainError):
    code = "model_not_found"
    public_message = "The requested model does not exist."


class NoAvailableModelError(DomainError):
    code = "no_available_model"
    public_message = "No model is currently available to serve this request."
    # Deliberately does not name the candidates that were considered.
    #
    # Until 2026-08-05 this was also the code for a runtime read timeout and a
    # stream that died half way — six distinct causes spanning three different
    # remedies, all telling the caller "retry with backoff" when for some of
    # them retrying could never work. The two subclasses below split off the
    # cases whose remedy differs; what remains here is "the routing layer found
    # nothing to send the request to", whose remedy really is backoff-then-
    # administrator.


class RuntimeTimeoutError(NoAvailableModelError):
    code = "runtime_timeout"
    public_message = (
        "The runtime did not respond within the time allowed. An immediate retry usually succeeds."
    )
    # A subclass, so anything catching NoAvailableModelError (routing tries the
    # next candidate) keeps working. The public message states the measured
    # property that makes this code worth its own name: after a prompt-
    # evaluation timeout the prompt sits in the runtime's prefix cache, so the
    # retry that was pointless for a missing routing policy is nearly free and
    # nearly certain here.


class StreamInterruptedError(NoAvailableModelError):
    code = "stream_interrupted"
    public_message = "The generation was interrupted before it finished."
    # The mid-stream death: the runtime stalled after producing bytes, or its
    # stream ended without a terminal event. Distinct from `runtime_timeout`
    # because the caller's position differs — they may hold a partial answer,
    # and whether to retry is a judgement about idempotence that only they can
    # make. Usually seen in the SSE error frame rather than as a status.


class ServerOverloadedError(DomainError):
    code = "overloaded"
    public_message = (
        "Every inference slot is busy and the queue wait elapsed. "
        "Retry after the interval in Retry-After."
    )
    # Before 2026-08-05 a request arriving with every slot held waited in an
    # unbounded, invisible queue: zero bytes, no code, death by the caller's
    # own client timeout — indistinguishable from a hung deployment. This is
    # the queue refusing loudly instead, and it is the code that finally makes
    # "busy" distinguishable from "broken".

    def __init__(self, retry_after_seconds: int = 60, detail: str | None = None) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds


class ModelStateConflictError(DomainError):
    code = "model_state_conflict"
    public_message = "The model is not in a state that allows this operation."


class InsufficientMemoryError(DomainError):
    code = "insufficient_memory"
    public_message = "Loading this model would exceed the node's memory budget."

    def __init__(self, required_gb: float, available_gb: float) -> None:
        super().__init__(f"required={required_gb} available={available_gb}")
        self.required_gb = required_gb
        self.available_gb = available_gb


class NodeNotFoundError(DomainError):
    code = "node_not_found"
    public_message = "The requested node does not exist."


class RuntimeUnavailableError(DomainError):
    code = "runtime_unavailable"
    public_message = "This deployment has no adapter for that runtime."
    # Caught at registration rather than at first use. A model bound to a
    # runtime nothing implements is a row that can never be downloaded or
    # loaded, and the failure would otherwise surface as a KeyError much later.


class InvalidModelReferenceError(DomainError):
    code = "invalid_model_reference"
    public_message = "The model reference is not valid."


class ContextTooLongError(DomainError):
    code = "context_too_long"
    public_message = "The conversation is longer than this platform accepts."


class AssistantUnavailableError(DomainError):
    code = "assistant_unavailable"
    public_message = (
        "The management assistant has no model to run on. "
        "An administrator can point the `assist` capability at one under Routing."
    )
    # Names the fix, unlike `NoAvailableModelError`, which deliberately does
    # not say which candidates were considered. The difference is the audience:
    # that error answers an anonymous caller on the public gateway, while this
    # one reaches only a signed-in operator on an admin entrance, who is either
    # able to write the routing policy or able to ask the person who is. Told
    # "no model is currently available" instead, they would go looking for a
    # busy node rather than for a policy that was never created.


# --- Prompt templates ----------------------------------------------------


class PromptTemplateNotFoundError(DomainError):
    code = "prompt_template_not_found"
    public_message = "That prompt template does not exist."
    # Same for another tenant's as for one that never existed, and the name a
    # caller sends is resolved by a tenant-scoped read, so a guessed name
    # cannot distinguish "not yours" from "not there".


# --- Knowledge base ------------------------------------------------------


class CollectionNotFoundError(DomainError):
    code = "collection_not_found"
    public_message = "That collection does not exist."
    # Raised for a collection in another tenant exactly as for one that never
    # existed, so the error cannot be used to probe what other tenants hold.


class DocumentNotFoundError(DomainError):
    code = "document_not_found"
    public_message = "That document does not exist."


class UploadRejectedError(DomainError):
    code = "upload_rejected"
    public_message = "This file cannot be accepted."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail)
        self.public_detail = detail
        """Unlike most errors here, the reason is safe to show: it describes the
        caller's own file (too large, wrong type) and reveals nothing about the
        platform. The router decides whether to include it."""


class DocumentParseError(DomainError):
    code = "document_parse_failed"
    public_message = "The document could not be read."
    # Never carries the parser's own message to the caller: it can quote
    # document bytes, which is the sensitive part of this feature.


class RuntimeCapabilityError(DomainError):
    code = "runtime_capability_unsupported"
    public_message = "That runtime cannot perform this operation."
    # Distinct from RuntimeUnavailableError, which means no adapter exists at
    # all. This one means the adapter exists and the runtime genuinely does not
    # do the thing, so refusing is the honest answer rather than a gap to fill.


class VectorStoreError(DomainError):
    code = "vector_store_unavailable"
    public_message = "The knowledge index is not available."


class DocumentStateConflictError(DomainError):
    code = "document_state_conflict"
    public_message = "The document is not in a state that allows this operation."


# --- Quota and rate limiting ---------------------------------------------


class QuotaExceededError(DomainError):
    code = "quota_exceeded"
    public_message = "The daily token quota for this key has been exhausted."


class RateLimitedError(DomainError):
    code = "rate_limited"
    public_message = "Too many requests."

    def __init__(self, retry_after_seconds: int = 60) -> None:
        super().__init__(f"retry_after={retry_after_seconds}")
        self.retry_after_seconds = retry_after_seconds


# --- Perimeter -----------------------------------------------------------


class CountryNotAllowedError(DomainError):
    code = "country_not_allowed"
    public_message = "Access from this location is not permitted."
    # Does not echo the detected country back to the caller.


class UntrustedProxyError(DomainError):
    code = "untrusted_proxy"
    public_message = "Request did not arrive through the expected path."


class InvalidCidrError(DomainError):
    code = "invalid_cidr"
    public_message = "One of the address ranges is not valid."


class InvalidNodeAddressError(DomainError):
    code = "invalid_node_address"
    public_message = "Node address must be inside the tailnet range."


class RetentionWindowTooShortError(DomainError):
    code = "retention_window_too_short"
    public_message = "Records must be kept for at least the minimum window."
    """Refused rather than clamped: storing a number the administrator did not
    type, and reporting success, puts the gap between what was chosen and what
    governs somewhere nobody re-reads."""


# --- Identity ------------------------------------------------------------


class NotAuthenticatedError(DomainError):
    code = "not_authenticated"
    public_message = "Authentication required."


class NotAuthorizedError(DomainError):
    code = "not_authorized"
    public_message = "You do not have permission to perform this action."
    # Does not reveal whether the target resource exists.


class InvalidCredentialsError(DomainError):
    code = "invalid_credentials"
    public_message = "Login or password is incorrect."
    # One message for both an unknown login and a wrong password. The use case
    # also runs a dummy hash for unknown accounts so timing does not
    # distinguish them either. The UI must not add a friendlier variant.


class TotpRequiredError(DomainError):
    code = "totp_required"
    public_message = "A verification code is required."


class InvalidTotpError(DomainError):
    code = "invalid_totp"
    public_message = "That verification code is not valid."
    # Also raised when a previously used counter is replayed.


class InvitationInvalidError(DomainError):
    code = "invitation_invalid"
    public_message = "This link is no longer valid."
    # Unknown, expired, and already-consumed tokens are indistinguishable.


class CsrfValidationError(DomainError):
    code = "csrf_failed"
    public_message = "The request could not be verified. Reload the page and try again."
    # 403 rather than 401 on purpose. A CSRF mismatch usually means a stale
    # page, not a dead session, and returning 401 would make the frontend sign
    # the user out over something a reload fixes.


class UserAlreadyExistsError(DomainError):
    code = "user_already_exists"
    public_message = "An account with that login already exists."
    # Unlike the login errors above, this one may name the situation: the only
    # caller is an authenticated administrator who can already list every user.


class UserNotFoundError(DomainError):
    code = "user_not_found"
    public_message = "That account does not exist."
    # Only ever raised for an authenticated administrator, who can already list
    # every account, so naming the situation reveals nothing.


class LastAdministratorError(DomainError):
    code = "last_administrator"
    public_message = "This is the only administrator left."
    # Removing or demoting them leaves an instance nobody can manage, and the
    # bootstrap setting does not come back: it is inert once any user exists.


class NoLocalCredentialsError(DomainError):
    code = "no_local_credentials"
    public_message = "This account has no password to change."
    # A tailnet-only account has nothing to re-enrol. Refused with a 4xx
    # rather than reaching a write that violates the users check constraint
    # and 500s.


class TotpEnrolmentExpiredError(DomainError):
    code = "totp_enrolment_expired"
    public_message = "The enrolment timed out. Start again."
    # The pending secret is held for minutes only, so a half-finished
    # re-enrolment cannot leave a usable second factor lying in the cache.


class WeakPasswordError(DomainError):
    code = "weak_password"
    public_message = "Choose a stronger password."

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        """Shown to the user: unlike the errors above, guidance here helps a
        legitimate user and tells an attacker nothing."""
