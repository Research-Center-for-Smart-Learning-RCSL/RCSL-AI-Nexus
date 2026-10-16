"""The per-node load lock's release, without a database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.persistence.node_serialisation import PostgresNodeSerialisation


class _Connection:
    def __init__(self, *, fail_unlock: bool) -> None:
        self._fail_unlock = fail_unlock
        self.invalidated = False

    async def execute(self, statement: Any, params: Any = None) -> Any:
        if "unlock" in str(statement):
            if self._fail_unlock:
                raise ConnectionError("lost")
            return SimpleNamespace(scalar_one=lambda: True)
        return SimpleNamespace(scalar_one=lambda: True)

    async def commit(self) -> None:
        return None

    async def invalidate(self) -> None:
        self.invalidated = True


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_Connection]:
        yield self._connection


async def test_a_failed_release_discards_the_connection_rather_than_pooling_the_lock() -> None:
    connection = _Connection(fail_unlock=True)
    lock = PostgresNodeSerialisation(lambda: _Engine(connection))  # type: ignore[arg-type,return-value]
    with pytest.raises(ConnectionError):
        async with lock.hold("node-1") as held:
            assert held
    assert connection.invalidated


async def test_a_clean_release_keeps_the_connection() -> None:
    connection = _Connection(fail_unlock=False)
    lock = PostgresNodeSerialisation(lambda: _Engine(connection))  # type: ignore[arg-type,return-value]
    async with lock.hold("node-1") as held:
        assert held
    assert not connection.invalidated
