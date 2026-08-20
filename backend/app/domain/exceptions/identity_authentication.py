"""Identity Authentication domain errors."""

from __future__ import annotations

from .base import DomainError, StateConflictError


class ApiKeyStateConflictError(StateConflictError):
    code = "api_key_state_conflict"
    public_message = "That change to the key is not allowed."


class ApiKeyLifetimeError(ApiKeyStateConflictError):
    """The one that cost an evening, and the one figure that ends it.

    `maximum_days` reaches the caller for the reason `ContextTooLongError`'s
    `limit` does: an operator refused at a boundary they cannot see has nothing
    to act on, and the boundary is a policy this deployment publishes rather
    than anything about its inventory. The date they typed is their own input
    described back to them, which is the test `interfaces/http/errors.py`
    already applies to `composition` and `UploadRejectedError.public_detail`.
    """

    code = "api_key_lifetime"

    def __init__(self, maximum_days: int, detail: str | None = None) -> None:
        super().__init__(detail)
        self.maximum_days = maximum_days
        self.public_message = (
            f"A key may not last longer than {maximum_days} days from today. "
            "Choose an earlier expiry date."
        )


class DebugWindowError(StateConflictError):
    code = "debug_window_invalid"
    public_message = "That debug window is not allowed."


class CountryNotAllowedError(DomainError):
    code = "country_not_allowed"
    public_message = "Access from this location is not permitted."


class UntrustedProxyError(DomainError):
    code = "untrusted_proxy"
    public_message = "Request did not arrive through the expected path."


class InvalidCidrError(DomainError):
    code = "invalid_cidr"
    public_message = "One of the address ranges is not valid."


class NotAuthenticatedError(DomainError):
    code = "not_authenticated"
    public_message = "Authentication required."


class NotAuthorizedError(DomainError):
    code = "not_authorized"
    public_message = "You do not have permission to perform this action."


class CapabilityNotIssuedError(NotAuthorizedError):
    code = "capability_not_issued"
    public_message = "That capability is not available to this key."
    """The one refusal in this family that names what it refused.

    A subclass rather than a looser message on the parent: `not_authorized` is
    deliberately opaque about whether the target exists, and every refusal on
    every entrance shares it. Widening that to help one case would widen it for
    all of them.

    This case can afford to be specific because it discloses nothing the caller
    does not already hold. The capability asked for is the one they just sent,
    and the list is the same answer `GET /v1/models` returns to the same key —
    so the message says out loud what one extra request would have said anyway.

    What that buys is a caller who can fix it. On 2026-08-14 two integrators
    sent the model name their client had picked for itself, and the only place
    the reason existed was this deployment's log: the operator had to read it
    for them, twice. The `model` field taking a capability rather than a model
    name is this platform's one real divergence from every other provider, and
    the refusal is exactly where somebody finds that out.
    """

    def __init__(
        self,
        *,
        capability: str,
        available: list[str],
        detail: str | None = None,
    ) -> None:
        self.capability = capability
        self.available = available
        # Assigned before `super().__init__`, which reads `public_message` when
        # no operator detail was given.
        self.public_message = (
            f"'{capability}' is not a capability this key may use. "
            f"Available: {', '.join(available)}. "
            "This platform's `model` field takes a capability, not a model name."
            if available
            # Says what is true — nothing is callable — without naming a cause.
            # An empty list has two of them: a key issued no capabilities, and a
            # key whose capabilities no routing policy currently serves, since
            # this list is `servable ∩ issuable ∩ the key's own`. Telling the
            # second case to reissue the key sends them to change the one thing
            # that is already right.
            else f"'{capability}' is not a capability this key may use, and this key "
            "can call nothing at present. An administrator can say whether that is "
            "the key's capabilities or the routing policies behind them."
        )
        super().__init__(detail)


class InvalidCredentialsError(DomainError):
    code = "invalid_credentials"
    public_message = "Login or password is incorrect."


class TotpRequiredError(DomainError):
    code = "totp_required"
    public_message = "A verification code is required."


class InvalidTotpError(DomainError):
    code = "invalid_totp"
    public_message = "That verification code is not valid."


class InvitationInvalidError(DomainError):
    code = "invitation_invalid"
    public_message = "This link is no longer valid."


class CsrfValidationError(DomainError):
    code = "csrf_failed"
    public_message = "The request could not be verified. Reload the page and try again."


class UserAlreadyExistsError(DomainError):
    code = "user_already_exists"
    public_message = "An account with that login already exists."


class UserNotFoundError(DomainError):
    code = "user_not_found"
    public_message = "That account does not exist."


class LastAdministratorError(DomainError):
    code = "last_administrator"
    public_message = "This is the only administrator left."


class NoLocalCredentialsError(DomainError):
    code = "no_local_credentials"
    public_message = "This account has no password to change."


class TotpEnrolmentExpiredError(DomainError):
    code = "totp_enrolment_expired"
    public_message = "The enrolment timed out. Start again."


class WeakPasswordError(DomainError):
    code = "weak_password"
    public_message = "Choose a stronger password."

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        """Shown to the user: unlike the errors above, guidance here helps a
        legitimate user and tells an attacker nothing."""
