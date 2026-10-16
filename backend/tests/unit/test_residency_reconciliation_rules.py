"""The pure rules the residency reconciler and the memory budget share (#49 §2)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.domain.entities.model import ModelState, ResourceProfile, RuntimeKind
from app.domain.services.residency_reconciliation import (
    AbsenceEvidence,
    backoff_seconds,
    charges_memory,
    observed_absent,
    restorable,
    restore_order,
)
from tests.unit.manage_models_fixtures import make_model

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _seen(observed: ModelState | None, seconds_ago: float = 5, **overrides: object):
    at = NOW - timedelta(seconds=seconds_ago) if observed is not None else None
    return make_model(observed_state=observed, observed_at=at, **overrides)


def test_backoff_doubles_from_thirty_seconds_and_caps_at_fifteen_minutes():
    assert [backoff_seconds(n) for n in range(1, 7)] == [30, 60, 120, 240, 480, 900]
    assert backoff_seconds(50) == 900


def test_restore_order_is_largest_declared_footprint_first():
    gemma = make_model(id="g", alias="gemma", resource_profile=ResourceProfile(44, 262144))
    qwen = make_model(id="q", alias="qwen", resource_profile=ResourceProfile(6, 32768))
    embed = make_model(id="e", alias="embedder", resource_profile=ResourceProfile(1, 2048))
    assert [m.alias for m in restore_order([embed, qwen, gemma])] == ["gemma", "qwen", "embedder"]


def test_only_a_fresh_positive_downloaded_observation_is_absence():
    assert observed_absent(_seen(ModelState.DOWNLOADED), NOW)
    assert not observed_absent(_seen(None), NOW)
    assert not observed_absent(_seen(ModelState.DOWNLOADED, seconds_ago=91), NOW)
    assert not observed_absent(_seen(ModelState.DOWNLOADED, seconds_ago=-5), NOW)
    assert not observed_absent(_seen(ModelState.LOADED), NOW)
    assert not observed_absent(_seen(ModelState.NOT_DOWNLOADED), NOW)


def test_evidence_counts_each_observation_once():
    evidence = AbsenceEvidence()
    first = _seen(ModelState.DOWNLOADED, seconds_ago=40)
    assert evidence.record(first, NOW) == 1
    # Re-reading the same answer is not a second answer.
    assert evidence.record(first, NOW) == 1
    second = replace(first, observed_at=NOW - timedelta(seconds=10))
    assert evidence.record(second, NOW) == 2


def test_unknown_or_resident_observation_restarts_the_count():
    evidence = AbsenceEvidence()
    evidence.record(_seen(ModelState.DOWNLOADED, seconds_ago=40), NOW)
    assert evidence.record(_seen(None), NOW) == 0
    assert evidence.record(_seen(ModelState.DOWNLOADED, seconds_ago=10), NOW) == 1
    assert evidence.record(_seen(ModelState.LOADED, seconds_ago=5), NOW) == 0


def test_a_gap_longer_than_the_freshness_window_does_not_chain():
    evidence = AbsenceEvidence()
    old = _seen(ModelState.DOWNLOADED, seconds_ago=5)
    evidence.record(old, NOW)
    later = NOW + timedelta(seconds=200)
    assert evidence.record(replace(old, observed_at=later - timedelta(seconds=1)), later) == 1


def test_occupancy_does_not_charge_a_fresh_positive_absence():
    intent_loaded = {"state": ModelState.LOADED}
    assert not charges_memory(_seen(ModelState.DOWNLOADED, **intent_loaded), NOW)
    assert charges_memory(_seen(ModelState.LOADED, **intent_loaded), NOW)
    # Unknown or stale: the last trustworthy value, which is the intent.
    assert charges_memory(_seen(None, **intent_loaded), NOW)
    assert charges_memory(_seen(ModelState.DOWNLOADED, seconds_ago=300, **intent_loaded), NOW)
    # Mid-load is charged whatever was observed before it.
    assert charges_memory(_seen(ModelState.DOWNLOADED, state=ModelState.LOADING), NOW)


def test_mlx_is_charged_on_intent_and_never_restored():
    mlx = _seen(None, runtime=RuntimeKind.MLX, state=ModelState.LOADED, desired_resident=True)
    assert charges_memory(mlx, NOW)
    assert not restorable(mlx, NOW)


def test_missing_weights_are_not_restorable():
    gone = _seen(ModelState.NOT_DOWNLOADED, desired_resident=True)
    assert not restorable(gone, NOW)
    assert restorable(_seen(ModelState.DOWNLOADED, desired_resident=True), NOW)
    assert not restorable(_seen(ModelState.DOWNLOADED, desired_resident=False), NOW)
