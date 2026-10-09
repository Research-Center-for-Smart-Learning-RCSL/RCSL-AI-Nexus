"""The node agent's host lock and its exclusion domain (design R1, S2 on #24)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.node_agent.lock_domain import (
    DOMAIN_NAME,
    LOCK_NAME,
    HostLock,
    LockDomainError,
    LockHeld,
    initialise,
    read_domain,
)

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "node_agent"


def _try_in_another_process(directory: Path) -> str:
    """Whether a separate process can take the lock: the case that matters."""
    code = (
        "import sys; from pathlib import Path\n"
        "from app.node_agent.lock_domain import HostLock, LockHeld\n"
        "try:\n"
        "    HostLock.acquire(Path(sys.argv[1])); print('ACQUIRED')\n"
        "except LockHeld:\n"
        "    print('BLOCKED')\n"
    )
    out = subprocess.run(  # noqa: S603 - a test driving a second interpreter
        [sys.executable, "-c", code, str(directory)],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    return out.stdout.strip()


def test_initialise_creates_a_domain_once(tmp_path: Path) -> None:
    first = initialise(tmp_path)
    second = initialise(tmp_path)

    assert first == second
    assert first.lock_inode == os.stat(tmp_path / LOCK_NAME).st_ino


def test_a_held_lock_excludes_another_process_until_the_holder_is_gone(tmp_path: Path) -> None:
    initialise(tmp_path)
    held = HostLock.acquire(tmp_path)

    assert _try_in_another_process(tmp_path) == "BLOCKED"

    held._close_for_tests()  # noqa: SLF001 - stands in for the holder's death
    assert _try_in_another_process(tmp_path) == "ACQUIRED"


def test_a_second_holder_in_the_same_process_is_refused(tmp_path: Path) -> None:
    """flock belongs to the open file description, so a second open in one
    process is a second claimant too."""
    initialise(tmp_path)
    held = HostLock.acquire(tmp_path)
    with pytest.raises(LockHeld):
        HostLock.acquire(tmp_path)
    held._close_for_tests()  # noqa: SLF001


def test_a_replaced_lock_file_is_refused_to_a_claimant(tmp_path: Path) -> None:
    """Locking a replacement inode while the original holder lives would let
    two senders each hold 'the' lock."""
    initialise(tmp_path)
    held = HostLock.acquire(tmp_path)
    os.unlink(tmp_path / LOCK_NAME)
    (tmp_path / LOCK_NAME).write_text("")

    with pytest.raises(LockDomainError, match="replaced"):
        HostLock.acquire(tmp_path)
    held._close_for_tests()  # noqa: SLF001


def test_the_holder_notices_an_unlinked_or_replaced_lock_file(tmp_path: Path) -> None:
    initialise(tmp_path)
    held = HostLock.acquire(tmp_path)
    assert held.still_held()

    os.unlink(tmp_path / LOCK_NAME)
    assert not held.still_held(), "unlinked"

    (tmp_path / LOCK_NAME).write_text("")
    assert not held.still_held(), "replaced"
    held._close_for_tests()  # noqa: SLF001


@pytest.mark.parametrize("keep", [LOCK_NAME, DOMAIN_NAME])
def test_half_a_domain_is_refused_rather_than_repaired(tmp_path: Path, keep: str) -> None:
    initialise(tmp_path)
    for name in (LOCK_NAME, DOMAIN_NAME):
        if name != keep:
            os.unlink(tmp_path / name)

    with pytest.raises(LockDomainError):
        initialise(tmp_path, settle_s=0.1)
    with pytest.raises(LockDomainError):
        read_domain(tmp_path)


def test_the_loser_of_a_first_start_reads_the_winners_domain(tmp_path: Path) -> None:
    """Review of #33's branch: a start that found the winner's lock file before
    its domain file was refused instead of reading it."""
    winner = initialise(tmp_path)
    domain = (tmp_path / DOMAIN_NAME).read_text()
    os.unlink(tmp_path / DOMAIN_NAME)
    writer = threading.Timer(0.2, (tmp_path / DOMAIN_NAME).write_text, args=(domain,))
    writer.start()
    try:
        assert initialise(tmp_path, settle_s=5) == winner
    finally:
        writer.join()


def test_a_separate_domain_is_a_different_identity(tmp_path: Path) -> None:
    """A second volume mints its own domain; the node binds the first one that
    claims it, so this identity is what a foreign claimant is refused by."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert initialise(tmp_path / "a").domain_id != initialise(tmp_path / "b").domain_id


def test_the_lock_descriptor_is_not_inherited(tmp_path: Path) -> None:
    initialise(tmp_path)
    held = HostLock.acquire(tmp_path)
    assert os.get_inheritable(held._fd) is False  # noqa: SLF001
    held._close_for_tests()  # noqa: SLF001


_FORBIDDEN_MODULES = {"subprocess", "multiprocessing"}
_FORBIDDEN_CALLS = {"fork", "forkpty", "posix_spawn", "posix_spawnp", "system", "popen"}


def test_the_agent_never_forks() -> None:
    """A forked child shares the open file description and keeps the flock
    alive after the agent dies, so a successor would wait on a process that is
    not the sender, or worse, a sender would survive in the child. O_CLOEXEC
    covers exec only; this rule covers fork (design revision 4)."""
    offences: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offences += [
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if a.name.split(".")[0] in _FORBIDDEN_MODULES
                ]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _FORBIDDEN_MODULES:
                    offences.append(f"{path.name}: from {node.module}")
                if node.module == "os":
                    offences += [
                        f"{path.name}: from os import {a.name}"
                        for a in node.names
                        if a.name in _FORBIDDEN_CALLS
                    ]
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in _FORBIDDEN_CALLS
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                offences.append(f"{path.name}:{node.lineno}: os.{node.attr}")
    assert offences == []
