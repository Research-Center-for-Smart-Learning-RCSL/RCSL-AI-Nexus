"""How long the append-only tables keep a row.

Four tables accumulate without an upper bound: `audit_log`, `usage_records`,
`prompt_logs` since 2026-08-08 and `refusals` since 2026-08-18. Everything
else in the schema is bounded by something a person decides — accounts, keys,
models, collections — and shrinks when they decide otherwise. Bounding these is therefore a policy
question rather than a capacity one, which is why the number lives in the
database and not in `.env`: it is meant to be argued about and changed by an
administrator, and every change is worth an audit entry.

The value is a **number of days**, not a cutoff date. A stored date would stop
meaning anything the moment nobody revisited it, and would silently stop
deleting; days are relative to now on every sweep and cannot go stale.

**The bound is not the same shape for every dataset, and `prompt_logs` is why.**
For the first two the danger is a window set too *short*: a week of audit
history is too little to investigate anything reported late, so they carry a
floor. For prompt transcripts the danger runs the other way. They hold the
message content §9.2 keeps out of the ordinary logs, they exist only for the
length of a debugging session, and the failure this whole control was designed
against is full logging switched on for an afternoon and left on for a year —
which a 360-day window would reproduce exactly, with an administrator who
believed they had configured something. So that dataset carries a **ceiling**,
and the ceiling is the part that is enforced. `RetentionBounds` exists so that
both readings live in one table rather than as a floor in the code and a
convention in somebody's memory.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType


class RetentionDataset(StrEnum):
    """What a policy can be set for, and what a purge can be aimed at.

    A closed set rather than a table name taken from the caller: these values
    reach a `DELETE`, and the whole reason this enum exists is that the set of
    things it is safe to delete from is decided here rather than at the edge.
    """

    AUDIT_LOG = "audit_log"
    """Who did what. Deletable, which is a decision rather than an oversight —
    see `security.md` §12.1 for what it costs and why it was made."""

    USAGE_RECORDS = "usage_records"
    """The accounting quotas are measured against. Its floor is not cosmetic:
    a window shorter than the longest quota period would make quota enforcement
    wrong rather than merely forgetful."""

    PROMPT_LOGS = "prompt_logs"
    """Full prompt and completion text, written only while a credential's debug
    window is open (§9.2). The one dataset here whose bound is a ceiling: it is
    the most sensitive data the platform holds and the shortest-lived reason for
    holding it."""

    REFUSALS = "refusals"
    """What callers were refused and why, in the words they were refused in.

    Carries a ceiling like `prompt_logs`, and for a weaker version of the same
    reason. It holds no request content — only codes, statuses, the message the
    caller received and the figures that came with it — so it is not the §9.2
    hazard. What it does accumulate is shape: a `composition` says a
    conversation was 97% one message, and a year of somebody's 413s is a
    description of how they work that nobody asked to have kept.
    """


DEFAULT_RETENTION_DAYS = 360
"""What the two metadata datasets start at.

Chosen by the administrator as one number for both, on the reasoning that a
year of history answers every question anybody has actually asked here and that
two different numbers would mean remembering which is which. 360 rather than
365 is the value as given; nothing in the code depends on it being either.

It was "what *every* dataset starts at" until `prompt_logs` arrived, and
applying it there would have been the bug this file now guards: a year of
retained prompt text, defaulted into rather than chosen.
"""

MINIMUM_RETENTION_DAYS = 30
"""The floor those two datasets may be set to.

Not a safety rail against typos so much as against a plausible-looking small
number: `7` reads as reasonable, and a week of audit history is too short to
investigate anything reported late. Anyone who genuinely wants less can purge
explicitly, which is a deliberate act with an entry of its own rather than a
standing rule that quietly forgets.
"""

DEFAULT_PROMPT_LOG_RETENTION_DAYS = 7
"""What `prompt_logs` starts at, and §9.2's "markedly shorter" made a number.

A debug window is capped at 24 hours, so a week keeps every transcript from a
session well past the point where anyone is still reading it, and keeps none
from the session before last.
"""

MAXIMUM_PROMPT_LOG_RETENTION_DAYS = 30
"""The ceiling `prompt_logs` may be set to.

A month is the outer edge of "we are still investigating this". Past it, what
is being kept is not a debugging artefact but a corpus of researchers'
unpublished ideas, which is the thing §9.2 exists to stop the platform
accumulating. An administrator who needs a specific transcript for longer can
copy it out deliberately; nothing here should make that the default by
inaction.
"""

DEFAULT_REFUSAL_RETENTION_DAYS = 30
"""What `refusals` starts at.

A month, because the question this table answers has a long tail: "we have been
getting this since the start of term" is asked here, and a week would already
have deleted the beginning of it. Longer than the transcripts above by a factor
of four and shorter than the metadata datasets by a factor of twelve, which is
where a record that is neither content nor accounting belongs.
"""

MAXIMUM_REFUSAL_RETENTION_DAYS = 180
"""The ceiling `refusals` may be set to.

Six months is the outer edge of a diagnosis. Past it what accumulates stops
being a record of things that went wrong and becomes a behavioural history of
the people who provoked them, which is the thing the ceiling exists to stop
being defaulted into.
"""

MINIMUM_REFUSAL_RETENTION_DAYS = 7
"""And a floor, unlike `prompt_logs`, because this table is read by the person
who was refused rather than by somebody who opened a window for an afternoon. A
window of a day would delete a refusal before the caller who provoked it on a
Friday came back to it on a Monday.
"""

MINIMUM_PROMPT_LOG_RETENTION_DAYS = 1
"""And a floor of a day, which is not the interesting bound but is a real one:
`0` would mean the sweep deletes a transcript in the same hour the operator
opened the window to read it.
"""


@dataclass(frozen=True, slots=True)
class RetentionBounds:
    """The three numbers that govern one dataset.

    A record rather than three parallel dicts, so that adding a dataset is one
    entry that cannot be half-added — the shape this file is most likely to be
    edited into next is a fourth `RetentionDataset` member, and the failure
    worth designing against is one whose bound nobody remembered to state.
    """

    default_days: int
    minimum_days: int
    maximum_days: int | None = None
    """None where growth is the thing being bounded rather than disclosure, so
    an administrator may keep audit history for as long as they care to."""


RETENTION_BOUNDS: Mapping[RetentionDataset, RetentionBounds] = MappingProxyType(
    {
        RetentionDataset.AUDIT_LOG: RetentionBounds(
            default_days=DEFAULT_RETENTION_DAYS,
            minimum_days=MINIMUM_RETENTION_DAYS,
        ),
        RetentionDataset.USAGE_RECORDS: RetentionBounds(
            default_days=DEFAULT_RETENTION_DAYS,
            minimum_days=MINIMUM_RETENTION_DAYS,
        ),
        RetentionDataset.PROMPT_LOGS: RetentionBounds(
            default_days=DEFAULT_PROMPT_LOG_RETENTION_DAYS,
            minimum_days=MINIMUM_PROMPT_LOG_RETENTION_DAYS,
            maximum_days=MAXIMUM_PROMPT_LOG_RETENTION_DAYS,
        ),
        RetentionDataset.REFUSALS: RetentionBounds(
            default_days=DEFAULT_REFUSAL_RETENTION_DAYS,
            minimum_days=MINIMUM_REFUSAL_RETENTION_DAYS,
            maximum_days=MAXIMUM_REFUSAL_RETENTION_DAYS,
        ),
    }
)
"""Every dataset's bounds, keyed by the dataset itself.

Read-only, and total: `bounds_for` raises rather than defaulting, because a
dataset missing from here would otherwise silently inherit a year.
"""


def bounds_for(dataset: RetentionDataset) -> RetentionBounds:
    bounds = RETENTION_BOUNDS.get(dataset)
    if bounds is None:  # pragma: no cover - unreachable while the table is total
        raise KeyError(f"no retention bounds declared for {dataset.value}")
    return bounds


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    dataset: RetentionDataset
    days: int
    updated_at: datetime | None = None
    updated_by: str | None = None
    """Display name of whoever last changed it, or null while it is still the
    default nobody has touched. Stored denormalised for the same reason the
    audit log stores it: the row must stay readable after the account is gone.
    """


@dataclass(frozen=True, slots=True)
class PurgeOutcome:
    """What a purge did, in the shape the screen reports and the audit records.

    `cutoff` is carried rather than recomputed: it is the only part a reader
    cannot derive afterwards, and "deleted 4,000 rows" without saying older than
    what is not a statement anyone can check.
    """

    dataset: RetentionDataset
    cutoff: datetime
    deleted: int
