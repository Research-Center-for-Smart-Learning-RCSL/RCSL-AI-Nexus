"""Retention Evaluations domain errors."""

from __future__ import annotations

from .base import DomainError


class RetentionWindowTooShortError(DomainError):
    code = "retention_window_too_short"
    public_message = "Records must be kept for at least the minimum window."
    """Refused rather than clamped: storing a number the administrator did not
    type, and reporting success, puts the gap between what was chosen and what
    governs somewhere nobody re-reads."""


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


class PromptLogNotFoundError(DomainError):
    code = "prompt_log_not_found"
    public_message = "That transcript does not exist."


class EvaluationRunNotFoundError(DomainError):
    code = "evaluation_run_not_found"
    public_message = "That evaluation run does not exist."
