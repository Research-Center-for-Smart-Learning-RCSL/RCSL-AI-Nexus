"""Inference Runtime domain errors."""

from __future__ import annotations

from .base import DomainError, StateConflictError


class ModelNotFoundError(DomainError):
    code = "model_not_found"
    public_message = "The requested model does not exist."


class NoAvailableModelError(DomainError):
    code = "no_available_model"
    public_message = "No model is currently available to serve this request."


class RuntimeTimeoutError(NoAvailableModelError):
    code = "runtime_timeout"
    public_message = (
        "The runtime did not respond within the time allowed. "
        "Retrying the same request unchanged is unlikely to help; send less."
    )


class StreamInterruptedError(NoAvailableModelError):
    code = "stream_interrupted"
    public_message = "The generation was interrupted before it finished."


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


class ModelStateConflictError(StateConflictError):
    code = "model_state_conflict"
    public_message = "The model is not in a state that allows this operation."


class InsufficientMemoryError(DomainError):
    code = "insufficient_memory"
    public_message = "Loading this model would exceed the node's memory budget."

    def __init__(self, required_gb: float, available_gb: float) -> None:
        super().__init__(f"required={required_gb} available={available_gb}")
        self.required_gb = required_gb
        self.available_gb = available_gb


class RuntimeUnavailableError(DomainError):
    code = "runtime_unavailable"
    public_message = "This deployment has no adapter for that runtime."


class InvalidModelReferenceError(DomainError):
    code = "invalid_model_reference"
    public_message = "The model reference is not valid."


class ModelIntegrityError(DomainError):
    code = "model_integrity_failed"
    public_message = "The downloaded weights do not match what the repository describes."


CONTEXT_REMEDY = (
    "Retrying it unchanged cannot succeed and waiting does not clear it: send less "
    "— start a new conversation, continue from a summary of this one, or stop "
    "reading large files into it."
)


COUNT_BY_TOKENIZER = "tokenizer"


COUNT_BY_ESTIMATE = "estimate"


COUNT_BY_LOWER_BOUND = "lower_bound"


def _count_phrase(basis: str, tokens: int) -> str:
    if basis == COUNT_BY_TOKENIZER:
        return f"{tokens:,} tokens"
    if basis == COUNT_BY_LOWER_BOUND:
        return f"at least {tokens:,} tokens"
    return f"an estimated {tokens:,} tokens"


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
        basis: str = COUNT_BY_ESTIMATE,
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
        self.basis = basis
        """How the figure was arrived at, which changes what the caller should
        conclude from it.

        Added 2026-08-17 with the tokeniser. Until then every refusal here was
        an estimate that ran 1.34x-1.48x high on ordinary content, so a caller
        refused at 140,059 could not tell whether they were near the limit or
        nowhere near it — and one of them was not. A figure counted with the
        model's own vocabulary is a different claim from one inferred from
        character widths, and a lower bound is a third; a caller deciding how
        much to trim needs to know which of the three they were handed.

        The field name `estimated` outlives its accuracy on purpose. It is on
        the wire, documented on `/api-docs`, and read by clients; renaming it
        to `counted` would break them to fix a word. This says what it is
        instead.
        """
        if estimated is not None and limit is not None:
            self.public_message = (
                f"This input is {_count_phrase(basis, estimated)} against a limit of "
                f"{limit:,}, counting tool definitions and every replayed turn. "
                f"{CONTEXT_REMEDY}"
            )


class RequestTooLargeError(DomainError):
    code = "request_too_large"
    public_message = "The request body is larger than this platform accepts."


class AssistantUnavailableError(DomainError):
    code = "assistant_unavailable"
    public_message = (
        "The management assistant has no model to run on. "
        "An administrator can point the `assist` capability at one under Routing."
    )


class RuntimeCapabilityError(DomainError):
    code = "runtime_capability_unsupported"
    public_message = "That runtime cannot perform this operation."


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
