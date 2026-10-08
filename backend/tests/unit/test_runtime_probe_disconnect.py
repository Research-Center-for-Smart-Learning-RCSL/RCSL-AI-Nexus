"""The disconnect probe's verdict, which decides what "cancelled" was measured.

Each case is one the review on #26 reproduced against an earlier version:
another task's cancellation, a task id that is a prefix of another, and a
release mistaken for a cancellation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[3] / "scripts" / "runtime-probes"
sys.path.insert(0, str(_DIR))
_spec = importlib.util.spec_from_file_location("runtime_probes_disconnect", _DIR / "disconnect.py")
assert _spec is not None and _spec.loader is not None
_disconnect = importlib.util.module_from_spec(_spec)
sys.modules["runtime_probes_disconnect"] = _disconnect
_spec.loader.exec_module(_disconnect)

START_101 = "slot   operator(): id  0 | task 101 | new prompt, n_ctx_slot = 32768, n_keep = 4"


def verdict(lines: list[str]) -> bool | None:
    task = _disconnect.stream_task([START_101])
    return _disconnect.cancellation_verdict(lines, task, chunks_read=5)[0]


def test_the_stream_is_the_only_task_started() -> None:
    assert _disconnect.stream_task([START_101]) == "101"
    assert _disconnect.stream_task([]) is None
    assert _disconnect.stream_task([START_101, START_101.replace("101", "102")]) is None


def test_its_own_cancellation_is_a_cancellation() -> None:
    assert verdict(["srv  stop: cancel task, id_task = 101"]) is True


def test_another_tasks_cancellation_is_not() -> None:
    assert verdict(["srv  stop: cancel task, id_task = 202"]) is None


def test_a_longer_id_with_the_same_prefix_is_another_task() -> None:
    assert verdict(["srv  stop: cancel task, id_task = 1010"]) is None


def test_a_release_is_not_a_cancellation() -> None:
    assert (
        verdict(["slot release: id  0 | task 101 | stop processing: n_tokens = 50, truncated = 0"])
        is None
    )
    assert (
        verdict(["slot release: id_slot = 0 id_task = 101 stop processing, n_tokens = 50,"]) is None
    )


def test_running_far_past_the_close_is_not_cancelled() -> None:
    lines = ["slot release: id  0 | task 101 | stop processing: n_tokens = 4000, truncated = 0"]
    assert verdict(lines) is False


def test_no_identified_stream_means_no_verdict() -> None:
    assert (
        _disconnect.cancellation_verdict(["cancel task, id_task = 101"], None, chunks_read=5)[0]
        is None
    )
