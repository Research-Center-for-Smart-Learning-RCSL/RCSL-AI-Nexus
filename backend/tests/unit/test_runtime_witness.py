"""The host runtime witness (scripts/host/runtime_witness.py, design S4/T1)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "host" / "runtime_witness.py"


@pytest.fixture(scope="module")
def witness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("runtime_witness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["runtime_witness"] = module
    spec.loader.exec_module(module)
    return module


# Rows shaped like macOS `netstat -anv -p tcp`: the owner is the `name:pid`
# field, after the buffer columns.
_ROW = "tcp4  0  0  {local}  *.*  LISTEN  0 0 131072 131072 {owner} 0 0x0100 0x00000006"
NETSTAT = "\n".join(
    [
        "Active Internet connections (including servers)",
        _ROW.format(local="127.0.0.1.11434", owner="ollama:812"),
        _ROW.format(local="192.168.1.5.11434", owner="other:999"),
        _ROW.format(local="127.0.0.1.8000", owner="com.docker:55"),
    ]
)


def test_only_the_endpoints_own_listener_is_its_owner(witness: ModuleType) -> None:
    assert witness.listener_owner(NETSTAT, "127.0.0.1", 11434) == ("ollama:812",)


def test_a_wildcard_listener_of_the_right_family_serves_loopback(witness: ModuleType) -> None:
    table = NETSTAT.replace("127.0.0.1.11434", "*.11434")
    assert witness.listener_owner(table, "127.0.0.1", 11434) == ("ollama:812",)


def test_only_a_well_formed_nonce_is_read(witness: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "challenge").write_text("a" * 32)
    assert witness.read_challenge(tmp_path) == "a" * 32
    (tmp_path / "challenge").write_text("$(rm -rf /)")
    assert witness.read_challenge(tmp_path) is None


def test_the_challenge_is_read_before_the_runtime_is_observed(
    witness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Design T1: an attestation carrying nonce N must be an observation taken
    after N was issued, so the read comes first."""
    order: list[str] = []
    monkeypatch.setattr(witness, "read_challenge", lambda d: order.append("read") or "b" * 32)

    def observe(endpoint: str) -> dict[str, Any]:
        order.append("observe")
        return {"status": "observed", "pid": 1, "start_time": "t"}

    monkeypatch.setattr(witness, "observe", observe)
    out = tmp_path / "out"
    out.mkdir()

    witness.cycle("http://127.0.0.1:11434", out, tmp_path, "inc", 7)

    assert order == ["read", "observe"]
    document = json.loads((out / "attestation.json").read_text())
    assert document["nonce"] == "b" * 32
    assert document["seq"] == 7 and document["witness_incarnation"] == "inc"
    assert document["endpoint"] == "127.0.0.1:11434"


def test_a_non_loopback_endpoint_is_inconclusive(witness: ModuleType) -> None:
    assert witness.observe("http://10.0.0.5:11434")["status"] == "inconclusive"
