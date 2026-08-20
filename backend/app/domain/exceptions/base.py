"""Base domain errors."""

from __future__ import annotations


class DomainError(Exception):
    code: str = "internal_error"
    public_message: str = "An internal error occurred."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.public_message)
        self.detail = detail
        """Operator-facing context. Written to the application log with the
        request id; never included in a response body."""


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
