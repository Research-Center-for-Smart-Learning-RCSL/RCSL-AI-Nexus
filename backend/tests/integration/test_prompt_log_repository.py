"""Transcripts against a real Postgres (security.md section 9.2).

Three properties the unit tests cannot reach, because each is a property of the
SQL rather than of the code that builds it:

- the tenant filter, which is a real `WHERE` clause and not a fake's notion of
  one, on both the paged read and the read-one;
- `list_summaries` genuinely not selecting the text, which is the difference
  between a design and a comment about a design;
- the retention sweep deleting from this table, whose default window is days
  rather than months and is therefore the one that runs first in production.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.mappers import prompt_log_to_row
from app.adapters.persistence.repositories import (
    PostgresPromptLogRepository,
    PostgresPromptLogWriter,
    PostgresRecordPurge,
)
from app.adapters.persistence.sqlalchemy_models import PromptLogRow
from app.domain.entities.prompt_log import PromptLogEntry

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

SECRET = "the unpublished result is 42"


@pytest.fixture
async def session(database_url):
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _entry(tenant_id: str, *, at: datetime = NOW, completion: str = SECRET) -> PromptLogEntry:
    return PromptLogEntry(
        id=str(uuid.uuid4()),
        at=at,
        actor_id="u1",
        api_key_id="k_abc",
        capability="chat",
        model_alias="primary",
        request_id="req_" + uuid.uuid4().hex[:12],
        messages='[{"role":"user","content":"what is it"}]',
        completion=completion,
        reasoning="",
        finish_reason="stop",
        completed=True,
        tool_calls=0,
        tenant_id=tenant_id,
    )


async def _store(session, entry: PromptLogEntry) -> None:
    """Put a row in this test's own transaction.

    The production writer commits in a session of its own, which is the whole
    point of it — but a committed row would outlive these tests, which roll
    back. So the rows here are staged directly; the writer's own behaviour is
    what `test_a_transcript_survives_the_request_that_failed` covers, and it is
    the only test that needs a real commit.
    """
    session.add(prompt_log_to_row(entry))
    await session.flush()


async def test_a_tenant_cannot_list_or_read_another_tenants_transcript(session) -> None:
    """The boundary this table most needs, on both reads.

    The read-one is called out separately because a primary-key fetch is where
    a tenant filter is easiest to omit: `session.get(PromptLogRow, id)` would
    work, return the row, and be wrong.
    """
    theirs = _entry("t-other")
    await _store(session, theirs)

    mine = PostgresPromptLogRepository(session, "t-mine")

    assert await mine.get(theirs.id) is None, "an id from another tenant reads as absent"
    assert (
        await mine.list_summaries(
            actor_id=None,
            api_key_id=None,
            capability=None,
            request_id=None,
            since=None,
            until=None,
            limit=50,
            offset=0,
        )
        == []
    )
    assert (
        await mine.count_entries(
            actor_id=None,
            api_key_id=None,
            capability=None,
            request_id=None,
            since=None,
            until=None,
        )
        == 0
    )


async def test_the_written_tenant_is_the_one_on_the_entity(database_url) -> None:
    """Where the tenant comes from, now that the writer takes no tenant.

    It rides on the entity, put there by `TranscriptBuffer.build` from the
    resolved actor — the same route usage takes on the gateway, where the
    repository is unscoped and stamps from the record. A caller never reaches
    it: `actor.tenant_id` is read from the API key row or the user row, not
    from anything in the request.

    A tenant parameter on the writer would be a second source for one value,
    and the reader is where the boundary is enforced anyway — see
    `test_a_tenant_cannot_list_or_read_another_tenants_transcript`.
    """
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    entry = _entry("t-research")
    try:
        await PostgresPromptLogWriter(factory).record(entry)

        async with factory() as reading:
            row = await reading.get(PromptLogRow, entry.id)
            assert row is not None
            assert row.tenant_id == "t-research"
    finally:
        async with factory() as cleanup:
            await cleanup.execute(text("DELETE FROM prompt_logs WHERE id = :i"), {"i": entry.id})
            await cleanup.commit()
        await engine.dispose()


async def test_the_summary_read_never_selects_the_message_text(session) -> None:
    """The design, asserted rather than described.

    A page of fifty transcripts carrying their text is a few hundred megabytes
    of the most sensitive data in the schema, pulled into the process to render
    a table. The lengths are computed by Postgres; only integers cross the wire.
    """
    stored = _entry("t-mine")
    await _store(session, stored)

    summaries = await PostgresPromptLogRepository(session, "t-mine").list_summaries(
        actor_id=None,
        api_key_id=None,
        capability=None,
        request_id=None,
        since=None,
        until=None,
        limit=50,
        offset=0,
    )

    (summary,) = summaries
    assert not hasattr(summary, "completion"), "the summary type carries no content field at all"
    assert summary.completion_chars == len(SECRET)
    assert summary.message_chars == len(stored.messages)
    assert summary.id == stored.id


async def test_a_transcript_survives_being_wider_than_any_bounded_column(session) -> None:
    """`audit_log` lost rows to a bounded column, silently, for months.

    A transcript is the widest value this schema stores, so the same choice
    here would drop precisely the rows somebody opened a window to read. 300k
    characters is past `MAX_FIELD_CHARS`, which the domain caps before this
    point — this asserts the column itself would not have been the limit.
    """
    wide = _entry("t-mine", completion="x" * 300_000)
    await _store(session, wide)

    read_back = await PostgresPromptLogRepository(session, "t-mine").get(wide.id)
    assert read_back is not None
    assert len(read_back.completion) == 300_000


async def test_the_request_id_finds_the_conversation(session) -> None:
    """The way in: a caller quotes the id from their error envelope and this
    turns that string into the conversation it names."""
    repo = PostgresPromptLogRepository(session, "t-mine")
    wanted = _entry("t-mine")
    await _store(session, wanted)
    await _store(session, _entry("t-mine"))

    found = await repo.list_summaries(
        actor_id=None,
        api_key_id=None,
        capability=None,
        request_id=wanted.request_id,
        since=None,
        until=None,
        limit=50,
        offset=0,
    )

    assert [s.id for s in found] == [wanted.id]


async def test_the_retention_sweep_deletes_from_this_table(session) -> None:
    """A policy nothing acts on deletes nothing.

    This dataset is the reason the sweep matters most: the other two are
    bounded for capacity over months, this one for disclosure over days. A
    sweep that silently stopped running would show up as a disk figure for
    those two and as retained prompt text for this one.
    """
    await _store(session, _entry("t-mine", at=NOW - timedelta(days=30)))
    await _store(session, _entry("t-mine", at=NOW - timedelta(days=1)))

    purge = PostgresRecordPurge(session, PromptLogRow)
    cutoff = NOW - timedelta(days=7)

    assert await purge.count_older_than(cutoff) == 1
    assert await purge.delete_older_than(cutoff) == 1
    assert await purge.count_older_than(NOW) == 1, "the recent one is untouched"


async def test_the_purge_crosses_tenants_deliberately(session) -> None:
    """Retention is platform-wide, held by an administrator who is not confined
    to a tenant. A purge that quietly spared other tenants would report a count
    that did not describe what it did."""
    await _store(session, _entry("t-a", at=NOW - timedelta(days=30)))
    await _store(session, _entry("t-b", at=NOW - timedelta(days=30)))

    deleted = await PostgresRecordPurge(session, PromptLogRow).delete_older_than(
        NOW - timedelta(days=7)
    )

    assert deleted == 2


async def test_the_migration_created_the_lookup_indexes(session) -> None:
    """Asserted against the database rather than the model, because the ORM's
    `Index` declarations and the migration are two separate statements of the
    same intent and only one of them runs in production."""
    rows = await session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'prompt_logs'")
    )
    names = {r[0] for r in rows}

    assert "ix_prompt_logs_tenant_at" in names, "the paged read's filter and sort"
    assert "ix_prompt_logs_request_id" in names, "the way in from an error envelope"


async def test_a_transcript_survives_the_request_that_failed(database_url) -> None:
    """The case a debug window is actually opened for.

    An operator opens a window because a caller reported an error. If the
    transcript is staged on the request's own session, the exception that
    produced that error rolls the session back and takes the transcript with
    it — so the one conversation somebody is looking for is the one that was
    never written, while every successful request around it recorded fine.

    Written against two real sessions rather than a fake, because the fake has
    no transaction and would pass either way. This is the property, not the
    mechanism: it must hold however the writer gets its session.
    """
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    entry = _entry("t-mine")

    try:
        # The unit of work the request runs in, ending the way a failed
        # generation ends: an exception out of `session_scope`. The writer is
        # handed the *factory*, which is the fix — it commits in a transaction
        # of its own, so the rollback below cannot reach it.
        async with factory() as work:
            try:
                await PostgresPromptLogWriter(factory).record(entry)
                raise RuntimeError("the runtime was unreachable")
            except RuntimeError:
                await work.rollback()

        async with factory() as reading:
            found = await PostgresPromptLogRepository(reading, "t-mine").get(entry.id)

        assert found is not None, (
            "the transcript for the failed request was rolled back with it, "
            "which is the request the window was opened for"
        )
    finally:
        async with factory() as cleanup:
            await cleanup.execute(text("DELETE FROM prompt_logs WHERE id = :i"), {"i": entry.id})
            await cleanup.commit()
        await engine.dispose()
