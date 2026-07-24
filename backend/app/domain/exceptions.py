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
