from __future__ import annotations

import sys
import time
from contextlib import aclosing

import pytest

from app.adapters.runtime.mlx_adapter import (
    ALLOWED_FILE_PATTERNS,
    MlxAdapter,
    is_allowed_file,
)
from app.domain.exceptions import (
    DomainError,
    InvalidModelReferenceError,
)
from tests.unit.mlx_adapter_fixtures import (
    REF,
)

pytest_plugins = ("tests.unit.mlx_adapter_fixtures",)


async def test_pull_reports_real_byte_progress(monkeypatch) -> None:
    """The download runs in a worker thread; progress is polled from the cache
    while it runs, so the sequence must climb from starting to success."""
    adapter = MlxAdapter("http://mlx.invalid", pull_poll_interval_seconds=0.02)
    seen_bytes = {"value": 0}

    monkeypatch.setattr(adapter, "_repo_total_bytes", lambda ref: 1000)

    def fake_download(ref: str) -> None:
        # Long enough that the poll loop runs at least once at 0.02s intervals.
        for step in (250, 500, 1000):
            seen_bytes["value"] = step
            time.sleep(0.03)

    monkeypatch.setattr(adapter, "_download_snapshot", fake_download)
    monkeypatch.setattr(adapter, "_downloaded_bytes", lambda ref: seen_bytes["value"])

    progress = []
    async with aclosing(adapter.pull(REF)) as s:
        async for item in s:
            progress.append(item)

    assert progress[0].status == "starting"
    assert progress[-1].status == "success"
    assert progress[-1].completed_bytes == 1000
    assert any(p.status == "downloading" for p in progress), "no progress was polled mid-download"
    # Monotonic non-decreasing bytes, which is what a progress bar depends on.
    seq = [p.completed_bytes for p in progress]
    assert seq == sorted(seq)


async def test_pull_maps_a_download_failure_to_a_domain_error(monkeypatch) -> None:
    adapter = MlxAdapter("http://mlx.invalid", pull_poll_interval_seconds=0.02)
    monkeypatch.setattr(adapter, "_repo_total_bytes", lambda ref: None)
    monkeypatch.setattr(adapter, "_downloaded_bytes", lambda ref: 0)

    def boom(ref: str) -> None:
        raise RuntimeError("network is down")

    monkeypatch.setattr(adapter, "_download_snapshot", boom)

    with pytest.raises(DomainError):
        async with aclosing(adapter.pull(REF)) as s:
            async for _ in s:
                pass


def test_validate_ref_accepts_a_repo_id_and_rejects_a_path() -> None:
    adapter = MlxAdapter("http://mlx.invalid")
    adapter.validate_ref(REF)  # does not raise
    adapter.validate_ref("gpt2")  # a bare canonical name is valid too
    with pytest.raises(InvalidModelReferenceError):
        adapter.validate_ref("mlx-community/../secrets")
    with pytest.raises(InvalidModelReferenceError):
        adapter.validate_ref("https://evil.example/model")


def test_a_download_fetches_only_formats_that_cannot_execute() -> None:
    """security.md 7.1(c) says only `.safetensors` and `.gguf` are acceptable.

    Until 2026-08-18 nothing enforced it: `snapshot_download` was called with
    no `allow_patterns` and fetched every file in the repository, including the
    pickle formats whose loading is equivalent to executing arbitrary code.
    This pins the enforcement point, because the claim it backs is written in a
    document that cannot check itself.
    """
    for name in (
        "model.safetensors",
        "model-00001-of-00002.safetensors",
        "model.safetensors.index.json",
        "model.gguf",
        "config.json",
        "tokenizer.json",
        "tokenizer.model",
        "merges.txt",
    ):
        assert is_allowed_file(name), name

    for name in (
        "pytorch_model.bin",
        "model.pt",
        "checkpoint.ckpt",
        "weights.pth",
        "anything.pkl",
        "flax_model.msgpack",
        "model.h5",
    ):
        assert not is_allowed_file(name), name


def test_the_allowlist_reaches_a_weight_file_in_a_subdirectory() -> None:
    """`snapshot_download` matches repository-relative paths, and sharded
    repositories put weights one level down. Matching only the base name would
    have counted such a file towards the progress total while the download
    skipped it, so the two have to agree."""
    assert is_allowed_file("weights/model-00001-of-00002.safetensors")
    assert not is_allowed_file("weights/pytorch_model.bin")


@pytest.mark.asyncio
async def test_the_download_call_carries_the_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """The patterns exist to be passed. A test on the constant alone would pass
    on a build where the argument had been dropped."""
    calls: list[dict[str, object]] = []

    class FakeHub:
        @staticmethod
        def snapshot_download(**kwargs: object) -> str:
            calls.append(kwargs)
            # The return value is the snapshot path; nothing under test reads it.
            return "snapshot-path"

    monkeypatch.setitem(sys.modules, "huggingface_hub", FakeHub)
    adapter = MlxAdapter("http://mlx.invalid")
    # Verification is exercised by the tests below; this one is about the
    # argument, and the seam deliberately does both.
    monkeypatch.setattr(adapter, "_verify_snapshot", lambda ref, path: None)
    adapter._download_snapshot(REF)

    assert calls == [{"repo_id": REF, "allow_patterns": list(ALLOWED_FILE_PATTERNS)}]
