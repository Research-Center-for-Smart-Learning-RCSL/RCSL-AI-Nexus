"""An operator's retry of the weights pin a pull could not set (#68 §3)."""

from __future__ import annotations

import pytest

from app.domain.entities.audit import AuditAction
from app.domain.exceptions import (
    ManifestPinRefusedError,
    ModelStateConflictError,
    NotAuthorizedError,
)
from app.domain.ports.model_runtime_port import ManifestPinPort
from app.interfaces.http.errors import public_details
from tests.unit.fakes import FakeRuntime
from tests.unit.manage_models_fixtures import ADMIN, READER, Harness, make_model

SERVED = "b" * 64


class PinningRuntime(FakeRuntime):
    """A node agent's runtime as far as the pin goes: it pins only what it serves."""

    def __init__(self, served: str = SERVED) -> None:
        super().__init__()
        self.served = served
        self.pinned: list[tuple[str, str]] = []

    async def repin(self, ref: str, manifest_digest: str) -> None:
        if manifest_digest != self.served:
            raise ManifestPinRefusedError(
                reason="digest_mismatch", served=self.served, measured=self.served
            )
        self.pinned.append((ref, manifest_digest))


def _repinned(harness: Harness) -> list[tuple[str, str]]:
    return [
        (outcome, detail.get("manifest_digest", ""))
        for _, action, _, outcome, detail in harness.audit.rows
        if action == AuditAction.MODEL_REPINNED
    ]


def test_only_a_runtime_with_a_pin_offers_it() -> None:
    assert isinstance(PinningRuntime(), ManifestPinPort)
    assert not isinstance(FakeRuntime(), ManifestPinPort)


async def test_the_served_weights_are_pinned_and_audited() -> None:
    runtime = PinningRuntime()
    harness = Harness([make_model()], runtime=runtime)

    await harness.use_case.repin(ADMIN, "m1", SERVED)

    assert runtime.pinned == [("library/qwen2.5:7b", SERVED)]
    assert _repinned(harness) == [("success", SERVED)]


async def test_a_refusal_is_audited_with_what_is_served_and_raised() -> None:
    harness = Harness([make_model()], runtime=PinningRuntime())

    with pytest.raises(ManifestPinRefusedError) as refused:
        await harness.use_case.repin(ADMIN, "m1", "c" * 64)

    assert refused.value.served == SERVED
    (row,) = [r for r in harness.audit.rows if r[1] == AuditAction.MODEL_REPINNED]
    assert row[3] == "failed"
    assert row[4] == {"manifest_digest": "c" * 64, "reason": "digest_mismatch", "served": SERVED}


async def test_a_runtime_without_a_pin_is_refused_before_anything_is_sent() -> None:
    harness = Harness([make_model()])

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.repin(ADMIN, "m1", SERVED)
    assert _repinned(harness) == []


async def test_it_needs_model_write() -> None:
    runtime = PinningRuntime()
    harness = Harness([make_model()], runtime=runtime)

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.repin(READER, "m1", SERVED)
    assert runtime.pinned == []


def test_a_refusal_tells_the_operator_what_is_served() -> None:
    """`detail` never leaves the process, so the figures must."""
    refused = ManifestPinRefusedError(reason="digest_mismatch", served=SERVED, measured=None)
    assert public_details(refused) == {
        "reason": "digest_mismatch",
        "served": SERVED,
        "measured": None,
    }
