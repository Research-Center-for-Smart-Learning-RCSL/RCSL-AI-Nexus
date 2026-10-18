"""Committed control-plane evidence, including expired unresolved operations."""

from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
)
from app.domain.entities.model import ModelState, RuntimeKind
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.infrastructure.availability import read_availability
from tests.integration.repository_fixtures import _model, _node


@pytest.fixture
async def snapshot_db(database_url):
    engine = create_async_engine(database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        now = (await session.execute(text("SELECT now()"))).scalar_one()
        await PostgresNodeRepository(session).save(_node())
        await PostgresModelRepository(session).save(
            replace(
                _model(),
                observed_state=ModelState.LOADED,
                observed_at=now,
            )
        )
        await PostgresRoutingPolicyRepository(session).save(
            RoutingPolicy("chat", (RoutingCandidate("primary", 100),))
        )
        await session.commit()
        yield session
    await engine.dispose()


async def read(session):
    # Availability resolves an adapter without ever calling it.
    return await read_availability(session, {RuntimeKind.OLLAMA: object()})


async def test_residency_loss_unknown_staleness_and_recovery(snapshot_db):
    session = snapshot_db
    assert next(c for c in (await read(session)).capabilities if c.capability == "chat").available
    for statement, reason in [
        ("observed_state = 'downloaded'", "model_not_resident"),
        ("observed_state = NULL, observed_at = NULL", "residency_unknown"),
        (
            "observed_state = 'loaded', observed_at = now() - interval '91 seconds'",
            "residency_stale",
        ),
        ("observed_state = 'loaded', observed_at = now()", None),
    ]:
        await session.execute(text("UPDATE models SET " + statement))  # noqa: S608 - constants above
        await session.commit()
        chat = next(c for c in (await read(session)).capabilities if c.capability == "chat")
        assert chat.available is (reason is None)
        assert chat.reasons == (() if reason is None else (reason,))


async def test_residency_mismatch_reads_committed_intent_and_fresh_evidence(snapshot_db):
    session = snapshot_db
    assert (await read(session)).residency_mismatch == {"primary": False}
    for statement, mismatched in [
        # Wanted and freshly resident.
        ("desired_resident = true", False),
        ("observed_state = 'downloaded'", True),
        ("observed_state = 'loaded', observed_at = now() - interval '91 seconds'", True),
        ("observed_state = 'loaded', observed_at = now()", False),
        # No longer wanted: absent weights are nobody's concern.
        ("desired_resident = false, observed_state = 'downloaded'", False),
    ]:
        await session.execute(text("UPDATE models SET " + statement))  # noqa: S608 - constants above
        await session.commit()
        assert (await read(session)).residency_mismatch == {"primary": mismatched}


async def test_request_transaction_does_not_make_a_new_heartbeat_look_future(snapshot_db):
    session = snapshot_db
    transaction_start = (await session.execute(text("SELECT now()"))).scalar_one()
    async with async_sessionmaker(session.bind, expire_on_commit=False)() as heartbeat:
        observed_at = (
            await heartbeat.execute(
                text(
                    "UPDATE models SET observed_state = 'loaded', observed_at = clock_timestamp() "
                    "RETURNING observed_at"
                )
            )
        ).scalar_one()
        await heartbeat.commit()
    assert observed_at > transaction_start
    # READ COMMITTED sees the new observation, despite the reader's older
    # transaction start; availability must evaluate it against current time.
    snapshot = await read(session)
    assert snapshot.at >= observed_at
    assert next(c for c in snapshot.capabilities if c.capability == "chat").available


async def test_unresolved_operation_blocks_until_explicit_resolution(snapshot_db):
    session = snapshot_db
    await session.execute(
        text("""
        INSERT INTO node_operations
            (node_id, op_id, kind, state, origin_generation, origin_boot_id, owner_generation,
             submitted_at)
        VALUES ('n1', 'op', 'summary', 'outcome_unknown', 1, 'boot', 1,
                now() - interval '7 days')
    """)
    )
    await session.commit()
    snapshot = await read(session)
    assert snapshot.unresolved == {"n1": 1}
    assert next(c for c in snapshot.capabilities if c.capability == "chat").reasons == (
        "node_operation_unresolved",
    )
    await session.execute(text("UPDATE node_operations SET state = 'failed'"))
    await session.commit()
    assert (await read(session)).unresolved == {"n1": 0}


async def test_silent_outage_uses_durable_rolling_window_and_only_gateway_refusals(snapshot_db):
    session = snapshot_db
    assert not (await read(session)).silent_outage
    await session.execute(
        text("""
        INSERT INTO refusals
            (id, tenant_id, actor_id, actor_display, at, code, status, surface, method,
             path, message, figures)
        VALUES ('r', 't', 'u', 'u', now(), 'no_available_model', 503, 'admin',
                'POST', '/v1/chat/completions', 'unavailable', '{}')
    """)
    )
    await session.commit()
    assert not (await read(session)).silent_outage
    await session.execute(text("UPDATE refusals SET surface = 'gateway'"))
    await session.commit()
    assert (await read(session)).silent_outage
    await session.execute(
        text("""
        INSERT INTO usage_records
            (id, tenant_id, actor_id, capability, model_alias, tokens, latency_ms, completed, at)
        VALUES ('u', 't', 'u', 'chat', 'primary', 1, 1, false, now())
    """)
    )
    await session.commit()
    assert (await read(session)).silent_outage
    await session.execute(text("UPDATE usage_records SET completed = true"))
    await session.commit()
    assert not (await read(session)).silent_outage
    await session.execute(text("UPDATE usage_records SET at = now() - interval '25 hours'"))
    await session.commit()
    assert (await read(session)).silent_outage
    await session.execute(text("UPDATE refusals SET at = now() - interval '25 hours'"))
    await session.commit()
    assert not (await read(session)).silent_outage
