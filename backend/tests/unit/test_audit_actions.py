"""Invariants of the audit action catalogue.

The catalogue's main guarantee is not tested here because it is not testable:
`AuditPort.record` takes `AuditAction`, so mypy refuses an action that is not a
member, at every call site, before anything runs.

What is left are the three ways a member could be added and still be wrong in a
way nothing else reports.
"""

from __future__ import annotations

import re

from app.adapters.audit.postgres_audit import _WIDTHS
from app.domain.entities.audit import AuditAction


def test_no_member_is_an_alias() -> None:
    """Two members sharing a value make the second an alias of the first.

    Iteration skips aliases, so the emitter would leave that action out of the
    frontend's list while `AuditAction.THE_ALIAS` kept working in the backend --
    exactly the drift the catalogue exists to remove, reintroduced from inside
    it.
    """
    assert len(AuditAction.__members__) == len(list(AuditAction))


def test_every_value_fits_the_audit_column() -> None:
    """`PostgresAudit._fit` trims an over-long value rather than losing the row.

    That is right for `target`, which is an unbounded request path. For an
    action it would be silent corruption: the trimmed name is written, the logs
    filter matches exactly, and the event becomes unfindable by the name the
    code uses for it.
    """
    for action in AuditAction:
        assert len(action.value) <= _WIDTHS["action"], action.name


def test_every_value_is_a_dotted_lowercase_name() -> None:
    """`subject.verb`, which is what the logs screen groups and sorts on."""
    shape = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    for action in AuditAction:
        assert shape.match(action.value), action.value
