"""The kernel-release CLI's refusals that need no database (#62, item 5)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest

from app.node_agent import release_kernel
from app.node_agent.lock_domain import HostLock, initialise

NODE = "33333333-3333-3333-3333-333333333333"
ARGS = [
    "--node",
    NODE,
    "--previous-kernel",
    "k1",
    "--current-kernel",
    "k2",
    "--operator",
    "ops",
    "--reason",
    "colima restarted",
]


@pytest.fixture
def lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "lock"
    directory.mkdir()
    initialise(directory)
    settings = SimpleNamespace(node_id=NODE, lock_dir=directory, dsn="postgresql://unused")
    monkeypatch.setattr(release_kernel, "AgentSettings", lambda: settings)
    monkeypatch.setattr(release_kernel, "kernel_boot_id", lambda: "k2")

    async def no_database(dsn: str) -> None:
        raise AssertionError("a refused release must not reach the database")

    monkeypatch.setattr(asyncpg, "connect", no_database)
    return directory


def _refusal(capsys: pytest.CaptureFixture[str], argv: list[str]) -> str:
    assert release_kernel.main(argv) == 1
    refused: str = json.loads(capsys.readouterr().out)["refused"]
    return refused


def _with(**changes: str) -> list[str]:
    argv = list(ARGS)
    for flag, value in changes.items():
        argv[argv.index(f"--{flag.replace('_', '-')}") + 1] = value
    return argv


@pytest.mark.usefixtures("lock_dir")
def test_another_node_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert "configured for node" in _refusal(capsys, _with(node="other"))


@pytest.mark.usefixtures("lock_dir")
def test_a_current_kernel_other_than_this_one_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "runs in kernel k2" in _refusal(capsys, _with(current_kernel="k3"))


def test_an_unreadable_kernel_is_refused(
    lock_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release_kernel, "kernel_boot_id", lambda: None)
    assert "cannot read its kernel" in _refusal(capsys, ARGS)


def test_a_running_agent_in_this_kernel_is_refused(
    lock_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = HostLock.acquire(lock_dir)
    try:
        assert "held by another live process" in _refusal(capsys, ARGS)
    finally:
        agent._close_for_tests()  # noqa: SLF001


def test_a_missing_domain_is_refused_not_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    settings = SimpleNamespace(node_id=NODE, lock_dir=empty, dsn="postgresql://unused")
    monkeypatch.setattr(release_kernel, "AgentSettings", lambda: settings)
    monkeypatch.setattr(release_kernel, "kernel_boot_id", lambda: "k2")
    assert "refusing to recreate" in _refusal(capsys, ARGS)
    assert not any(empty.iterdir())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"operator": " "}, "an operator and a reason"),
        ({"reason": ""}, "an operator and a reason"),
        ({"previous_kernel": "k2"}, "are the same"),
    ],
)
async def test_statements_are_checked_before_any_lock(
    tmp_path: Path, changes: dict[str, str], message: str
) -> None:
    directory = tmp_path / "lock"
    directory.mkdir()
    initialise(directory)
    lock = HostLock.acquire(directory)
    arguments = {
        "previous_kernel_boot_id": changes.get("previous_kernel", "k1"),
        "current_kernel_boot_id": "k2",
        "operator": changes.get("operator", "ops"),
        "reason": changes.get("reason", "colima restarted"),
    }
    try:
        with pytest.raises(release_kernel.ReleaseRefused, match=message):
            await release_kernel.release_previous_kernel(
                None,  # refused before any query
                NODE,
                lock,
                **arguments,
            )
    finally:
        lock._close_for_tests()  # noqa: SLF001
