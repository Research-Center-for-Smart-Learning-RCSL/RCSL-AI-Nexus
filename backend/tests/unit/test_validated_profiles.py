"""The validated-profile catalogue holds only what was measured (PR2b on #24).

Review point 4: the evidence for a record is whole-prompt runtime counts for
every claimed shape, the actual encoder and renderer identity, and executed
`P ≤ U` checks; a skipped real-weight suite cannot grant validation. So:

- without weights, each record is checked against the code: its cases exist
  and have exactly its shape, and the Python encoder it names is the one this
  checkout builds (an edit to the encoder withdraws the record, visibly);
- with weights, the manifest, the renderer and every case's count are checked
  against the store, and the native encoder too when it is built.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.adapters.tokenizer.gguf_token_counter import fingerprint
from app.adapters.tokenizer.gguf_token_counter.adapter import GgufTokenCounter
from app.domain.services.validated_profiles import (
    VALIDATED,
    WIRE_THINKING,
    ProfileKey,
    ValidatedProfile,
    fresh_version,
    is_validated,
    servable,
    wire_thinking,
)
from tests.unit.runtime_validation_corpus import CASES, RECORDED, wire_payload

try:
    import nexus_native
except ImportError:  # pragma: no cover
    nexus_native = None

PROFILES = [pytest.param(p, id=f"{p.ref}-tools={p.tools}") for p in VALIDATED]


def _recorded(profile: ValidatedProfile) -> dict[str, object]:
    entry = next(
        (e for e in RECORDED.values() if profile.manifest.startswith(str(e["manifest"]))), None
    )
    assert entry is not None, f"no recorded runtime counts for {profile.manifest[:12]}"
    return entry


@pytest.mark.parametrize("profile", PROFILES)
def test_a_record_stands_on_recorded_cases_of_exactly_its_shape(profile: ValidatedProfile) -> None:
    entry = _recorded(profile)
    assert entry["ollama"] == profile.runtime_version
    assert profile.thinking <= set(WIRE_THINKING)
    seen_thinking: set[str] = set()
    for name in profile.cases:
        assert name in entry["cases"], f"{name} has no recorded runtime count"  # type: ignore[operator]
        case = CASES[name]
        assert bool(case.tools) == profile.tools, f"{name} is another tool shape"
        body = wire_payload(profile.ref, case, 32768)
        seen_thinking.add("omitted" if "think" not in body else str(body["think"]).lower())
    assert seen_thinking == set(profile.thinking), "every claimed thinking mode is measured"


@pytest.mark.parametrize("profile", PROFILES)
def test_the_python_encoder_named_is_the_one_this_code_builds(profile: ValidatedProfile) -> None:
    python = {e for e in profile.encoders if e.startswith("python:")}
    assert python == {fingerprint.python_encoder()}, (
        "the encoder changed since this record was measured; measure it again"
    )


@pytest.mark.skipif(nexus_native is None, reason="the native extension is not built")
@pytest.mark.parametrize("profile", PROFILES)
def test_the_native_encoder_named_is_the_one_built(profile: ValidatedProfile) -> None:
    assert fingerprint.native_encoder(nexus_native.source_digest()) in profile.encoders


@pytest.mark.parametrize("profile", PROFILES)
def test_with_the_weights_every_case_bounds_the_runtime(profile: ValidatedProfile) -> None:
    root = os.environ.get("OLLAMA_MODELS_PATH")
    if not root:
        pytest.skip("OLLAMA_MODELS_PATH is not set")
    counter = GgufTokenCounter(Path(root))
    entry = _recorded(profile)
    for name in profile.cases:
        case = CASES[name]
        measured = asyncio.run(counter.measure(profile.ref, list(case.messages), list(case.tools)))
        assert measured.identity == profile.manifest
        assert measured.renderer == profile.renderer
        assert measured.encoder in profile.encoders
        runtime = entry["cases"][name]["count"]  # type: ignore[index]
        assert measured.counted is not None and runtime <= measured.counted, name


# -- matching ---------------------------------------------------------------

KEY = ProfileKey(
    node_id="local",
    runtime="ollama",
    runtime_version="0.33.2",
    manifest="845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
    encoder="python:x",
    renderer="jinja:r",
    tools=False,
    thinking="false",
)
PROFILE = ValidatedProfile(
    ref="m",
    node_id="local",
    runtime="ollama",
    runtime_version="0.33.2",
    manifest=KEY.manifest,
    encoders=frozenset({"python:x"}),
    renderer="jinja:r",
    tools=False,
    thinking=frozenset({"false"}),
    measured_on="2026-10-09",
    cases=(),
)


@pytest.mark.parametrize(
    "change",
    [
        {"node_id": "b"},
        {"runtime_version": "0.40.2"},
        {"manifest": "0" * 64},
        {"encoder": "python:y"},
        {"renderer": "jinja:other"},
        {"tools": True},
        {"thinking": "omitted"},
    ],
)
def test_any_part_of_the_fingerprint_that_differs_falls_back(change: dict[str, object]) -> None:
    from dataclasses import replace

    assert is_validated(KEY, (PROFILE,)) is PROFILE
    assert is_validated(replace(KEY, **change), (PROFILE,)) is None  # type: ignore[arg-type]


def test_a_stale_version_is_no_version() -> None:
    now = datetime(2026, 10, 9, 12, tzinfo=UTC)
    assert fresh_version("0.33.2", now - timedelta(minutes=1), now) == "0.33.2"
    assert fresh_version("0.33.2", now - timedelta(minutes=6), now) is None
    assert fresh_version(None, now, now) is None


def test_widening_drops_the_half_and_keeps_the_output_bound() -> None:
    assert servable(32768, 1536, widened=False) == 16384
    assert servable(32768, 1536, widened=True) == 31231
    assert servable(32768, 16384, widened=True) == 16383
    assert wire_thinking(True) == "omitted" and wire_thinking(False) == "false"
