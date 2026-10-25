"""The maintenance hold stops detached indexing between runtime batches (#61).

Ingestion hands a whole document's passages to `embed_with` in one call and
`EmbedTexts` splits them into batches, so the check has to run per batch, not
per call. The real `_DetachedEmbedder` and `EmbedTexts` batching are driven
here; only the database and the runtime are replaced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from app.application.use_cases.embed_texts import MAX_BATCH
from app.domain.entities.maintenance import NORMAL, MaintenancePhase
from app.domain.exceptions import MaintenanceError
from app.infrastructure import jobs
from tests.unit.fakes import FakeMaintenance

CLOSED = replace(NORMAL, admission_closed=True, phase=MaintenancePhase.MAINTENANCE, epoch=1)


class CountingMaintenance(FakeMaintenance):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    async def read(self):  # type: ignore[no-untyped-def]
        self.reads += 1
        return await super().read()


class Runtime:
    def __init__(self, on_call=None) -> None:  # type: ignore[no-untyped-def]
        self.calls: list[int] = []
        self._on_call = on_call

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        if self._on_call is not None:
            self._on_call()
        return [[0.0] for _ in texts]


@pytest.fixture
def maintenance(monkeypatch: pytest.MonkeyPatch) -> CountingMaintenance:
    hold = CountingMaintenance()

    @asynccontextmanager
    async def no_database() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(jobs, "session_scope", no_database)
    monkeypatch.setattr(jobs, "PostgresMaintenanceRepository", lambda _session: hold)
    return hold


PASSAGES = ["passage"] * (2 * MAX_BATCH + 1)
"""65 passages: three runtime batches."""


async def test_a_hold_that_begins_during_a_batch_stops_the_next_one(
    maintenance: CountingMaintenance,
) -> None:
    def close() -> None:
        maintenance.state = CLOSED

    runtime = Runtime(on_call=close)

    with pytest.raises(MaintenanceError):
        await jobs._DetachedEmbedder({}).embed_with(runtime, PASSAGES, "embedder")  # type: ignore[arg-type]

    assert runtime.calls == [MAX_BATCH]
    assert maintenance.reads == 2


async def test_the_hold_is_read_afresh_before_every_batch(
    maintenance: CountingMaintenance,
) -> None:
    runtime = Runtime()

    vectors = await jobs._DetachedEmbedder({}).embed_with(runtime, PASSAGES, "embedder")  # type: ignore[arg-type]

    assert len(vectors) == len(PASSAGES)
    assert runtime.calls == [MAX_BATCH, MAX_BATCH, 1]
    assert maintenance.reads == 3
