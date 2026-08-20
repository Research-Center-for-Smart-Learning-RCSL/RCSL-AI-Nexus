from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from app.adapters.runtime.mlx_adapter import (
    MlxAdapter,
    _git_blob_sha1_of,
)
from app.domain.exceptions import (
    DomainError,
)
from tests.unit.mlx_adapter_fixtures import (
    REF,
    _hub,
    _Sibling,
)

pytest_plugins = ("tests.unit.mlx_adapter_fixtures",)


def test_the_git_blob_hash_is_the_one_git_itself_computes(tmp_path: Path) -> None:
    """`blob_id` is a git object id, not a hash of the contents.

    Getting the framing wrong — the `blob <len>\0` prefix — produces a digest
    that never matches and would refuse every small file in every repository,
    so this is pinned against a value git printed rather than against itself.
    """
    f = tmp_path / "x"
    f.write_bytes(b"hello")
    assert _git_blob_sha1_of(f) == "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"


def test_a_snapshot_whose_digests_match_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")
    config = tmp_path / "config.json"
    config.write_bytes(b"{}")

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        _hub(
            [
                _Sibling("model.safetensors", sha256=hashlib.sha256(b"weights").hexdigest()),
                _Sibling("config.json", blob_id=_git_blob_sha1_of(config)),
            ]
        ),
    )

    MlxAdapter("http://mlx.invalid")._verify_snapshot(REF, tmp_path)
    assert weights.exists() and config.exists()


def test_a_file_whose_sha256_disagrees_is_refused_and_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleted, not merely reported: the next `load` reads this directory, so
    leaving the bytes there makes the check theatre."""
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"not what the repository describes")

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        _hub([_Sibling("model.safetensors", sha256=hashlib.sha256(b"weights").hexdigest())]),
    )

    with pytest.raises(DomainError) as caught:
        MlxAdapter("http://mlx.invalid")._verify_snapshot(REF, tmp_path)

    assert "sha256" in str(caught.value)
    assert not weights.exists()


def test_a_small_file_is_checked_by_its_git_object_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    config.write_bytes(b"{}")

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        _hub([_Sibling("config.json", blob_id=_git_blob_sha1_of(tmp_path / "config.json"))]),
    )
    MlxAdapter("http://mlx.invalid")._verify_snapshot(REF, tmp_path)

    config.write_bytes(b'{"changed": true}')
    with pytest.raises(DomainError):
        MlxAdapter("http://mlx.invalid")._verify_snapshot(REF, tmp_path)


def test_a_file_the_repository_does_not_describe_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An allowlisted extension is not a licence to arrive unannounced."""
    stray = tmp_path / "extra.safetensors"
    stray.write_bytes(b"surprise")

    monkeypatch.setitem(sys.modules, "huggingface_hub", _hub([]))

    with pytest.raises(DomainError) as caught:
        MlxAdapter("http://mlx.invalid")._verify_snapshot(REF, tmp_path)

    assert "not described" in str(caught.value)
    assert not stray.exists()


def test_a_file_with_no_stated_digest_is_refused_rather_than_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"weights")

    monkeypatch.setitem(sys.modules, "huggingface_hub", _hub([_Sibling("model.safetensors")]))

    with pytest.raises(DomainError) as caught:
        MlxAdapter("http://mlx.invalid")._verify_snapshot(REF, tmp_path)

    assert "no digest" in str(caught.value)
