"""How long the append-only tables keep a row.

Two tables accumulate without an upper bound, and only two: `audit_log` and
`usage_records`. Everything else in the schema is bounded by something a person
decides — accounts, keys, models, collections — and shrinks when they decide
otherwise. Bounding these two is therefore a policy question rather than a
capacity one, which is why the number lives in the database and not in `.env`:
it is meant to be argued about and changed by an administrator, and every
change is worth an audit entry.

The value is a **number of days**, not a cutoff date. A stored date would stop
meaning anything the moment nobody revisited it, and would silently stop
deleting; days are relative to now on every sweep and cannot go stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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


DEFAULT_RETENTION_DAYS = 360
"""What every dataset starts at.

Chosen by the administrator as one number for everything, on the reasoning that
a year of history answers every question anybody has actually asked here and
that two different numbers would mean remembering which is which. 360 rather
than 365 is the value as given; nothing in the code depends on it being either.
"""

MINIMUM_RETENTION_DAYS = 30
"""The floor a policy may be set to.

Not a safety rail against typos so much as against a plausible-looking small
number: `7` reads as reasonable, and a week of audit history is too short to
investigate anything reported late. Anyone who genuinely wants less can purge
explicitly, which is a deliberate act with an entry of its own rather than a
standing rule that quietly forgets.
"""


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
