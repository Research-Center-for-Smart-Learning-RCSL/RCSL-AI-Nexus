"""The probes' sizing search, which decides what a boundary measurement measured.

`boundary.py` reports "kept at num_ctx - 1, halved at num_ctx"; that claim is
only as good as the search that produced a prompt of exactly that many tokens.
These run it against a fake runtime whose count is non-linear and jumps by more
than one, which is what a real tokenizer does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "runtime-probes" / "_common.py"
_spec = importlib.util.spec_from_file_location("runtime_probes_common", _PATH)
assert _spec is not None and _spec.loader is not None
_common = importlib.util.module_from_spec(_spec)
sys.modules["runtime_probes_common"] = _common
_spec.loader.exec_module(_common)
size_to_runtime_count = _common.size_to_runtime_count


def _fake_count(n: int) -> int:
    # 40 tokens of framing, then roughly 1 token per 3.7 characters, with a
    # 2-token jump every 50 characters: monotone, not linear, not unit-step.
    return 40 + int(n / 3.7) + 2 * (n // 50)


@pytest.mark.parametrize("target", [41, 100, 1_000, 8_191, 8_192, 30_000])
def test_it_settles_on_the_target_or_the_largest_count_below_it(target: int) -> None:
    calls: list[int] = []

    def count(n: int) -> int:
        calls.append(n)
        return _fake_count(n)

    payload, got = size_to_runtime_count(target, lambda n: n, count, first_guess=target * 3)

    assert got == _fake_count(payload), "the count returned is the count of the payload returned"
    assert got <= target
    reachable_below = max(
        _fake_count(n) for n in range(0, payload + 400) if _fake_count(n) <= target
    )
    assert got == reachable_below, (got, reachable_below)
    assert len(calls) <= 18


def test_a_target_below_the_empty_payload_returns_the_empty_payload() -> None:
    payload, got = size_to_runtime_count(10, lambda n: n, _fake_count, first_guess=100)

    assert (payload, got) == (0, 40)
