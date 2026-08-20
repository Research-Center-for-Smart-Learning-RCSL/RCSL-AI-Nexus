"""HTTP mapping boundary."""

from __future__ import annotations

from app.domain.exceptions import (
    AssistantUnavailableError,
    CollectionNotFoundError,
    ContextTooLongError,
    CountryNotAllowedError,
    CsrfValidationError,
    DocumentNotFoundError,
    DocumentParseError,
    DocumentStateConflictError,
    DomainError,
    EvaluationRunNotFoundError,
    InsufficientMemoryError,
    InvalidCidrError,
    InvalidCredentialsError,
    InvalidModelReferenceError,
    InvalidNodeAddressError,
    InvalidTotpError,
    InvitationInvalidError,
    LastAdministratorError,
    ModelIntegrityError,
    ModelNotFoundError,
    NoAvailableModelError,
    NodeNotFoundError,
    NoLocalCredentialsError,
    NotAuthenticatedError,
    NotAuthorizedError,
    PromptLogNotFoundError,
    PromptTemplateNotFoundError,
    QuotaExceededError,
    RateLimitedError,
    RequestTooLargeError,
    RetentionWindowTooLongError,
    RetentionWindowTooShortError,
    RuntimeCapabilityError,
    RuntimeUnavailableError,
    ServerOverloadedError,
    StateConflictError,
    TotpEnrolmentExpiredError,
    TotpRequiredError,
    UntrustedProxyError,
    UploadRejectedError,
    UserAlreadyExistsError,
    UserNotFoundError,
    VectorStoreError,
    WeakPasswordError,
)

STATUS_MAP: dict[type[DomainError], int] = {
    ModelNotFoundError: 404,
    NoAvailableModelError: 503,
    AssistantUnavailableError: 503,
    StateConflictError: 409,
    InsufficientMemoryError: 409,
    InvalidModelReferenceError: 400,
    ModelIntegrityError: 502,
    ContextTooLongError: 413,
    RequestTooLargeError: 413,
    QuotaExceededError: 429,
    RateLimitedError: 429,
    CountryNotAllowedError: 403,
    UntrustedProxyError: 400,
    InvalidNodeAddressError: 400,
    RetentionWindowTooShortError: 400,
    PromptLogNotFoundError: 404,
    EvaluationRunNotFoundError: 404,
    RetentionWindowTooLongError: 400,
    NotAuthenticatedError: 401,
    NotAuthorizedError: 403,
    InvalidCredentialsError: 401,
    TotpRequiredError: 401,
    InvalidTotpError: 401,
    InvitationInvalidError: 400,
    WeakPasswordError: 400,
    UserAlreadyExistsError: 409,
    TotpEnrolmentExpiredError: 400,
    CsrfValidationError: 403,
    NodeNotFoundError: 404,
    RuntimeUnavailableError: 400,
    InvalidCidrError: 400,
    UserNotFoundError: 404,
    LastAdministratorError: 409,
    NoLocalCredentialsError: 409,
    CollectionNotFoundError: 404,
    PromptTemplateNotFoundError: 404,
    DocumentNotFoundError: 404,
    DocumentStateConflictError: 409,
    # 413, not 400: the common rejection is size, and a caller that sees 413
    # knows to send less rather than to send something different.
    UploadRejectedError: 413,
    DocumentParseError: 422,
    RuntimeCapabilityError: 400,
    VectorStoreError: 503,
    ServerOverloadedError: 503,
    # RuntimeTimeoutError and StreamInterruptedError are absent on purpose:
    # they subclass NoAvailableModelError and inherit its 503 through the MRO
    # walk below, so the split stays a split of *codes*, not of statuses.
}


OPENAI_ERROR_TYPES: dict[int, str] = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    409: "conflict_error",
    # 413 was absent until 2026-08-07 and fell through to `api_error`, the value
    # `handle_unanticipated` uses for a 500. So both `context_too_long` and
    # `request_too_large` — the caller's own request being too big, permanent
    # until they send less — announced themselves to every OpenAI client library
    # as a server-side fault, which is the one classification that invites a
    # retry. That is the split-by-remedy rule in `domain/exceptions.py` losing
    # in the last translation before the wire.
    413: "invalid_request_error",
    429: "rate_limit_error",
    503: "service_unavailable",
}


OPENAI_ERROR_TYPE_OVERRIDES: dict[type[DomainError], str] = {
    # Status is the wrong key for this one. 429 carries two conditions whose
    # remedies are opposite — back off and retry, or stop and ask for more
    # budget — and `backend.md` §5 has said since the gateway shipped that
    # clients must branch on the code to tell them apart. The `type` field is
    # the only half of that a client library reads: OpenAI's own error classes
    # are selected from it, and `insufficient_quota` is where they put "this
    # will not succeed by waiting".
    #
    # Sending `rate_limit_error` for an exhausted quota therefore asked every
    # OpenAI-compatible client to do the one thing that could not work. On
    # 2026-08-14 a Codex session did exactly that against key 68953ceb and
    # reported `exceeded retry limit, last status: 429` — a message about its
    # own backoff, naming neither the quota nor the key, to an operator with no
    # way to reach either from it.
    QuotaExceededError: "insufficient_quota",
}


def _status_for(exc: DomainError) -> int:
    for klass in type(exc).__mro__:
        if klass in STATUS_MAP:
            return STATUS_MAP[klass]
    return 500


def _openai_type_for(exc: DomainError, status: int) -> str:
    """Walked over the MRO for the same reason `_status_for` is: a subclass
    added later inherits the classification its parent was given, rather than
    silently falling back to the status map."""
    for klass in type(exc).__mro__:
        if klass in OPENAI_ERROR_TYPE_OVERRIDES:
            return OPENAI_ERROR_TYPE_OVERRIDES[klass]
    return OPENAI_ERROR_TYPES.get(status, "api_error")
