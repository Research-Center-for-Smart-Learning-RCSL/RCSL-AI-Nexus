"""Admin retention schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities.retention import RetentionPolicy, bounds_for


class RetentionPolicyResponse(BaseModel):
    dataset: str
    days: int
    updated_at: datetime | None
    updated_by: str | None
    """Null while the dataset is still on the default nobody has changed, which
    the screen shows as "default" rather than as an empty author."""

    minimum_days: int
    maximum_days: int | None
    """The bounds this dataset's window may be set within, sent rather than
    mirrored.

    **The screen used to carry its own copy of `RETENTION_BOUNDS`, and adding a
    fourth dataset broke it.** `refusals` arrived on 2026-08-18 and the form had
    no bounds for it, no label for it, and — because the frontend's dataset enum
    is what parses the response — no way to render the page at all: every
    retention policy failed to load behind one unrecognised value, on a screen
    whose own docstring claimed a fourth dataset would appear without a frontend
    change. Two tables that must agree, in two languages, with nothing failing
    until somebody opened the page.

    `None` where growth rather than disclosure is what is bounded, which is the
    shape `audit_log` and `usage_records` have; a number where the danger runs
    the other way, as it does for `prompt_logs` and `refusals`.
    """

    @classmethod
    def of(cls, policy: RetentionPolicy) -> RetentionPolicyResponse:
        bounds = bounds_for(policy.dataset)
        return cls(
            dataset=policy.dataset.value,
            days=policy.days,
            updated_at=policy.updated_at,
            updated_by=policy.updated_by,
            minimum_days=bounds.minimum_days,
            maximum_days=bounds.maximum_days,
        )


class RetentionPreviewResponse(BaseModel):
    dataset: str
    days: int
    affected: int


class PurgeOutcomeResponse(BaseModel):
    dataset: str
    cutoff: datetime
    deleted: int


class SetRetentionPolicyRequest(BaseModel):
    days: int = Field(ge=1)
    """`ge=1` only keeps the field a positive number; the real floor is
    `MINIMUM_RETENTION_DAYS` and is enforced in the use case, so a caller that
    never touches this schema meets the same rule."""
