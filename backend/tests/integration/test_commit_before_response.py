"""A write is committed before its response is sent (#45).

FastAPI exits a request-scoped `yield` dependency after the response has gone
out, and `get_session` commits on exit. So until #45 an admin write's 200
reached the client before the row was visible to anyone else: a read issued
straight back could be served the old state, which is the intermittent
`routing-selection` e2e failure, and a commit that failed reached nobody.

The probe sits where the client sits: it wraps the ASGI app and, at the
moment the response's status line is sent, asks a separate connection whether
the row is there. An in-process client cannot observe this by reading back
afterwards, because it returns only once the app has finished.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.admin_api_end_to_end_fixtures import NODE_ID, admin_client
from tests.integration.conftest import TEST_DATABASE_URL

ALIAS = "visible-at-response"


def _probing(app: Any, seen: list[int]) -> Any:
    """`app`, recording how many `models` rows carry ALIAS when a POST's
    status line is sent, read on a connection of its own."""

    async def probe(scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await app(scope, receive, send)
            return

        async def observed(message: dict) -> None:
            if message["type"] == "http.response.start":
                engine = create_async_engine(str(TEST_DATABASE_URL), poolclass=NullPool)
                try:
                    async with engine.connect() as connection:
                        count = await connection.scalar(
                            text("SELECT count(*) FROM models WHERE alias = :alias"),
                            {"alias": ALIAS},
                        )
                finally:
                    await engine.dispose()
                seen.append(int(count or 0))
            await send(message)

        await app(scope, receive, observed)

    return probe


@pytest.fixture
def probed() -> Iterator[tuple[TestClient, list[int]]]:
    """The admin client, its app wrapped by the probe."""
    seen: list[int] = []
    with admin_client(lambda app: _probing(app, seen)) as client:
        yield client, seen


def test_a_write_is_visible_to_another_connection_when_its_response_is_sent(
    probed: tuple[TestClient, list[int]],
) -> None:
    client, seen = probed

    created = client.post(
        "/admin/models",
        json={
            "alias": ALIAS,
            "ref": "library/qwen2.5:7b",
            "runtime": "ollama",
            "node_id": NODE_ID,
            "capabilities": ["chat"],
            "resource_profile": {"memory_gb": 8.0, "context_length": 32768},
        },
    )

    assert created.status_code == 201, created.text
    assert seen == [1]
