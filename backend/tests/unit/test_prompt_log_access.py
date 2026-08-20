from __future__ import annotations

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.read_prompt_logs import ReadPromptLogs
from app.domain.entities.actor import Scope
from app.domain.exceptions import NotAuthorizedError, PromptLogNotFoundError
from tests.unit.fakes import FakeAudit
from tests.unit.prompt_logging_fixtures import (
    RecordingTranscripts,
    _one_stored_transcript,
    reader,
)

pytest_plugins = ("tests.unit.prompt_logging_fixtures",)


async def test_listing_requires_the_scope_and_writes_no_audit_row() -> None:
    """Listing discloses no message content, and `prompt_log.list` on every
    page refresh would be noise that describes no disclosure. The row that
    matters is written when a conversation is actually read."""
    transcripts = await _one_stored_transcript()
    trail = FakeAudit()
    use_case = ReadPromptLogs(transcripts, RoleAuthorization(), trail)

    with pytest.raises(NotAuthorizedError):
        await use_case.list_page(reader(Scope.LOGS_READ))

    await use_case.list_page(reader(Scope.PROMPT_LOG_READ))
    assert trail.entries == []


async def test_reading_a_transcript_is_audited_by_id() -> None:
    """The question this control exists to make answerable. Opening a window
    has been audited since the switch shipped; who then read what it captured
    had no answer at all until now."""
    transcripts = await _one_stored_transcript()
    stored = transcripts.entries[0]
    trail = FakeAudit()
    use_case = ReadPromptLogs(transcripts, RoleAuthorization(), trail)

    entry = await use_case.read_transcript(reader(Scope.PROMPT_LOG_READ), stored.id)

    assert entry.completion == "Dyma 'r ateb."
    assert ("prompt_log.read", stored.id, "success") in trail.entries


async def test_the_audit_row_carries_no_message_content() -> None:
    """The one way this feature could undo its own bound.

    `audit_log` keeps 360 days; `prompt_logs` keeps 7. A snippet copied into
    the audit detail would outlive by a year the record the retention ceiling
    exists to expire, and it would do so in a table nothing about this feature
    would ever look at again.
    """
    transcripts = await _one_stored_transcript()
    stored = transcripts.entries[0]
    trail = FakeAudit()
    use_case = ReadPromptLogs(transcripts, RoleAuthorization(), trail)

    await use_case.read_transcript(reader(Scope.PROMPT_LOG_READ), stored.id)

    detail = [row for row in trail.rows if row[1] == "prompt_log.read"][0][4]
    serialised = " ".join(f"{k}={v}" for k, v in detail.items())
    assert "unpublished result" not in serialised
    assert "Welsh" not in serialised
    assert "Dyma" not in serialised
    assert detail["capability"] == "chat"


async def test_an_unknown_transcript_is_not_found_rather_than_refused() -> None:
    """The repository is tenant-scoped, so another tenant's id resolves to
    nothing. Answering "forbidden" would confirm the row exists, which is a
    cross-tenant read of one bit — and an expired transcript, which is the
    common case at a seven-day window, is genuinely absent."""
    trail = FakeAudit()
    use_case = ReadPromptLogs(RecordingTranscripts(), RoleAuthorization(), trail)

    with pytest.raises(PromptLogNotFoundError):
        await use_case.read_transcript(reader(Scope.PROMPT_LOG_READ), "no-such-id")

    assert trail.entries == [], "a read that disclosed nothing must not claim it did"
