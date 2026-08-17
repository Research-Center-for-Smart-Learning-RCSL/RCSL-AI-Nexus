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
        "The runtime did not respond within the time allowed. "
        "Retrying the same request unchanged is unlikely to help; send less."
    )
    # A subclass, so anything catching NoAvailableModelError (routing tries the
    # next candidate) keeps working.
    #
    # **The advice was the opposite of this until 2026-08-14, and it was
    # wrong.** It said an immediate retry usually succeeds, on the stated
    # ground that a prompt evaluated up to the timeout sits in the runtime's
    # prefix cache and so costs nothing the second time. Measured that day, by
    # aborting a cold prefill part way and re-sending it: the retry evaluated
    # 20,919 tokens in 33.5 seconds, the full cold rate, having kept nothing.
    # A cancelled prefill is discarded.
    #
    # So the one case this code exists to name — a prompt too long to evaluate
    # inside `request_timeout_seconds` — is precisely the case where retrying
    # fails again, identically, after the same wait. Telling an agent client to
    # retry it bought the caller another ten minutes per attempt and a
    # conversation it could never send. The prefix cache is real and does make
    # an agent's *next turn* nearly free; it just does not survive a
    # cancellation, which is the only way this error is reached.


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


class StateConflictError(DomainError):
    """409 — the thing being edited is not in a state that allows this.

    **Subclassed per subject because the message names the subject, and for
    most of this platform's history it named the wrong one.** Until 2026-08-17
    `ModelStateConflictError` was the general 409: 34 raises across eleven
    modules, only eleven of them about models, every one of them answering
    "The model is not in a state that allows this operation." An operator
    editing an API key's expiry was told about models, in a UI that renders
    `public_message` verbatim, while the reason — a 365-day maximum — sat in
    `detail`, which never leaves the process. They read it as the capability
    edit being rejected, tried seven times, and the capability had in fact
    saved. A refusal that names the wrong noun is worse than one that names
    nothing: it sends the reader somewhere.

    The status lives here rather than on each subclass because `_status_for`
    walks the MRO, so a subject added later is a 409 without anybody
    remembering to say so.
    """

    code = "state_conflict"
    public_message = "That change is not allowed in the current state."


class ModelStateConflictError(StateConflictError):
    code = "model_state_conflict"
    public_message = "The model is not in a state that allows this operation."


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


class PromptTemplateStateConflictError(StateConflictError):
    code = "prompt_template_state_conflict"
    public_message = "That change to the template is not allowed."


class RoutingPolicyStateConflictError(StateConflictError):
    code = "routing_policy_state_conflict"
    public_message = "That routing policy cannot be saved as written."


class NodeStateConflictError(StateConflictError):
    code = "node_state_conflict"
    public_message = "The node is not in a state that allows this operation."


class TenantStateConflictError(StateConflictError):
    code = "tenant_state_conflict"
    public_message = "That change to the tenant is not allowed."


class UserStateConflictError(StateConflictError):
    code = "user_state_conflict"
    public_message = "That change to the account is not allowed."


class CollectionStateConflictError(StateConflictError):
    code = "collection_state_conflict"
    public_message = "That change to the collection is not allowed."


class DebugWindowError(StateConflictError):
    code = "debug_window_invalid"
    public_message = "That debug window is not allowed."


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


CONTEXT_REMEDY = (
    "Retrying it unchanged cannot succeed and waiting does not clear it: send less "
    "— start a new conversation, continue from a summary of this one, or stop "
    "reading large files into it."
)


class ContextTooLongError(DomainError):
    code = "context_too_long"
    public_message = (
        "The input is longer than this platform accepts, counting tool definitions "
        f"and every replayed turn. {CONTEXT_REMEDY}"
    )
    # Carried a remedy from 2026-08-17, having been the one 413 without one.
    # `RuntimeTimeoutError` below has said "send less" since the gateway
    # shipped, and this — where sending less is the *only* thing that works —
    # said only that the conversation was too long, to a caller with no way to
    # tell a permanent refusal from a transient one. A Codex session that day
    # retried it six times in seven seconds, which is what a message with no
    # remedy invites.
    #
    # "Input", not "conversation": tool definitions alone can exceed the
    # ceiling, and a caller told to start a new conversation over definitions
    # their client resends every turn would be following advice that cannot
    # work.

    def __init__(
        self,
        detail: str | None = None,
        *,
        estimated: int | None = None,
        limit: int | None = None,
        composition: str | None = None,
    ) -> None:
        """The figures a caller needs to act, which reach them unlike `detail`.

        This is the second deliberate exception to "no internal detail in
        responses" (§9.2's debug window is the first), decided on 2026-08-17
        and narrower than it looks. `composition` and `estimated` describe the
        caller's own payload back to them and disclose nothing they did not
        send — the argument `_validation_message` and
        `UploadRejectedError.public_detail` already make in
        `interfaces/http/errors.py`.

        `limit` is the part that discloses something, and it was weighed rather
        than assumed harmless: the deployment ceiling is already published to
        every integrator on the Agents page, but the per-target ceiling added
        the same day is half a specific model's registered context, so a caller
        who provokes one on a fallback learns roughly how large that model is.
        That was accepted because the alternative is worse — a caller refused at
        a number they cannot see, on a capability that served them yesterday,
        has nothing to act on. The model's *name* is still withheld; see
        `RouteChatRequest._refuse_what_this_target_would_truncate`.

        Woven into `public_message` as well as carried as fields, because the
        fields are only read by code that knows to look and `message` is what
        every OpenAI client library prints. Codex swallows the body on this path
        entirely, which is why the runbook and the log line exist too; this is
        for the clients that do not.
        """
        super().__init__(detail)
        self.estimated = estimated
        self.limit = limit
        self.composition = composition
        if estimated is not None and limit is not None:
            self.public_message = (
                f"This input is an estimated {estimated:,} tokens against a limit of "
                f"{limit:,}, counting tool definitions and every replayed turn. "
                f"{CONTEXT_REMEDY}"
            )


class RequestTooLargeError(DomainError):
    code = "request_too_large"
    public_message = "The request body is larger than this platform accepts."
    # Deliberately distinct from ContextTooLongError, which shares its 413.
    # That one is counted in tokens after the body has been parsed and the
    # caller authenticated; this one is counted in bytes before either, so it
    # is the only 413 an anonymous caller can provoke. Telling them apart is
    # what lets an operator read a spike of one and not the other.


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


def _approximate_wait(seconds: int) -> str:
    """A duration a human can act on, not a number they must divide.

    Deliberately coarse. The figure it describes is a projection from the
    current contents of a rolling window, and quoting "8 hours 41 minutes"
    would claim a precision that the next request to the same key destroys.
    """
    if seconds < 90:
        return "a moment"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"about {minutes} minutes"
    hours = round(seconds / 3600)
    return "about an hour" if hours == 1 else f"about {hours} hours"


class QuotaExceededError(DomainError):
    code = "quota_exceeded"
    public_message = "The daily token quota for this key has been exhausted."

    def __init__(
        self, detail: str | None = None, *, retry_after_seconds: int | None = None
    ) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds
        """Seconds until the quota admits another request, or None when that
        could not be determined. Unlike `RateLimitedError` this has no sensible
        default: the window is 24 hours long and rolling, so the wait is
        anything from a minute to a day, and a guess is what the caller was
        already given — see the `Retry-After` note in interfaces/http/errors.py.
        """

        if retry_after_seconds is not None:
            # Set on the instance, so the class constant stays the answer when
            # the wait is unknown. Telling callers when their own key recovers
            # discloses nothing they could not measure by retrying, and it is
            # the one fact that turns this refusal into something they can act
            # on: an agent CLI reports the status line, and "429" alone sent
            # the operator of key 68953ceb to a maintainer on 2026-08-14.
            self.public_message = (
                f"{QuotaExceededError.public_message} "
                f"It recovers in {_approximate_wait(retry_after_seconds)}."
            )


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


class PromptLogNotFoundError(DomainError):
    code = "prompt_log_not_found"
    public_message = "That transcript does not exist."
    # For another tenant's transcript exactly as for one that never existed, and
    # for one the retention sweep has already removed — which is the common case
    # here rather than a corner, the window being days rather than months. A
    # bookmarked transcript that has expired reads as absent, which is correct:
    # it is absent.


class EvaluationRunNotFoundError(DomainError):
    code = "evaluation_run_not_found"
    public_message = "That evaluation run does not exist."
    # Reached by a bookmark to a run that has since been deleted, and by a
    # re-import that replaced a label with a fresh id. Both are absences rather
    # than refusals, so neither says anything about what else is stored.


class RetentionWindowTooLongError(DomainError):
    code = "retention_window_too_long"
    public_message = "This record type may not be kept for that long."
    """The mirror of the error above, and the one that governs `prompt_logs`.

    A separate code rather than a reused one because the two mean opposite
    things to whoever reads them: too-short says the platform is about to
    forget something it needs, too-long says it is about to keep something it
    should not. A client that collapsed them would give the same advice for
    both, and one of the two pieces of advice would be wrong.
    """


# --- Identity ------------------------------------------------------------


class NotAuthenticatedError(DomainError):
    code = "not_authenticated"
    public_message = "Authentication required."


class NotAuthorizedError(DomainError):
    code = "not_authorized"
    public_message = "You do not have permission to perform this action."
    # Does not reveal whether the target resource exists.


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
