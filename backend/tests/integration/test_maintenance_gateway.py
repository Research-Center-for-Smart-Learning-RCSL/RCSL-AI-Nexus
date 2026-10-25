"""The gateway during a maintenance hold (#61): every key refused with 503
`maintenance`, nothing reaching the runtime, and the same key working again
once the hold is lifted."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.chat_end_to_end_fixtures import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

pytest_plugins = ("tests.integration.chat_end_to_end_fixtures",)


async def _hold(closed: bool) -> None:
    """Written the way the admin use case writes it, from outside the app, so
    the gateway can only learn of it by reading the row."""
    engine = create_async_engine(TEST_DATABASE_URL or "")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE maintenance_control SET admission_closed = :closed, "
                "phase = CASE WHEN :closed THEN 'maintenance' ELSE 'normal' END, "
                "epoch = epoch + CASE WHEN :closed THEN 1 ELSE 0 END, "
                "revision = revision + 1 WHERE id = 1"
            ),
            {"closed": closed},
        )
    await engine.dispose()


async def test_every_key_is_refused_with_maintenance_and_resumes_unchanged(client) -> None:
    test_client, runtime, _ = client
    assert test_client.get("/v1/models").status_code == 200

    await _hold(True)

    listed = test_client.get("/v1/models")
    assert listed.status_code == 503, listed.text
    assert listed.json()["error"]["code"] == "maintenance"
    assert listed.json()["error"]["type"] == "service_unavailable"
    assert listed.headers["Retry-After"] == "60"

    chat = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert chat.status_code == 503, chat.text
    assert chat.json()["error"]["code"] == "maintenance"
    assert runtime.seen_ref is None, "a refused request reached the runtime"

    await _hold(False)

    assert test_client.get("/v1/models").status_code == 200
    resumed = test_client.post(
        "/v1/chat/completions",
        json={"model": "chat", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resumed.status_code == 200, resumed.text


async def test_a_bad_key_is_still_told_it_is_unauthenticated(client) -> None:
    """The hold is checked after the key is known, so a caller without a valid
    key learns nothing new from it: the public status already says the same."""
    test_client, _, _ = client
    await _hold(True)
    test_client.headers["Authorization"] = "Bearer nope"
    assert test_client.get("/v1/models").status_code == 401
    await _hold(False)
