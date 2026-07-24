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


class WeakPasswordError(DomainError):
    code = "weak_password"
    public_message = "Choose a stronger password."

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        """Shown to the user: unlike the errors above, guidance here helps a
        legitimate user and tells an attacker nothing."""
