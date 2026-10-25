"""The host runtime supervisor (scripts/host/runtime_supervisor.py, P3 on #61).

Driven against a simulated host: a process table, a launchd job that respawns
its daemon while loaded, and signals that end processes. What is pinned is the
contract the root job promises: a fixed set of actions, a stop that leaves no
runtime process and no loaded job, no signal to a reused PID, and each request
executed at most once with a receipt.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "host" / "runtime_supervisor.py"
UID = 251
LABEL = "online.rcsl.ollama"


@pytest.fixture(scope="module")
def sv() -> ModuleType:
    spec = importlib.util.spec_from_file_location("runtime_supervisor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["runtime_supervisor"] = module
    spec.loader.exec_module(module)
    return module


class FakeHost:
    """ps, launchctl and kill, as far as the supervisor uses them."""

    def __init__(self) -> None:
        self.next_pid = 500
        self.clock = 0.0
        self.procs: dict[int, dict[str, Any]] = {}
        self.loaded = True
        self.daemon: int | None = None
        self.signals: list[tuple[int, int]] = []
        self.runners_ignore_bootout = False
        self.daemon_ignores_term = False
        self.bootstrap_fails = False
        self.spawn("/opt/homebrew/opt/ollama/bin/ollama", daemon=True)
        self.spawn("/opt/homebrew/Cellar/ollama/0.40.8/bin/ollama", parent=self.daemon)
        self.spawn("/usr/sbin/syslogd", uid=0)
        self.spawn("/bin/zsh", uid=UID)

    def spawn(
        self, command: str, *, uid: int = UID, parent: int | None = 1, daemon: bool = False
    ) -> int:
        self.next_pid += 1
        pid = self.next_pid
        self.procs[pid] = {
            "ppid": parent,
            "uid": uid,
            "lstart": f"Sun Oct 25 10:{pid % 60:02d}:00 2026",
            "command": command,
        }
        if daemon:
            self.daemon = pid
        return pid

    def runner(self, argv: Sequence[str]) -> tuple[int, str]:
        if argv[0] == "/bin/ps":
            rows = [
                f"{pid} {p['ppid']} {p['uid']} {p['lstart']} {p['command']}"
                for pid, p in self.procs.items()
            ]
            return 0, "\n".join(rows) + "\n"
        if argv[:2] == ["/bin/launchctl", "print"]:
            if not self.loaded:
                return 113, "Could not find service"
            return 0, f"system/{LABEL} = {{\n\tpid = {self.daemon}\n}}\n" if self.daemon else "{}"
        if argv[:2] == ["/bin/launchctl", "bootout"]:
            self.loaded = False
            if self.daemon is not None:
                self.procs.pop(self.daemon, None)
                self.daemon = None
            if not self.runners_ignore_bootout:
                for pid in [
                    p for p, d in self.procs.items() if d["uid"] == UID and "ollama" in d["command"]
                ]:
                    self.procs.pop(pid)
            return 0, ""
        if argv[:2] == ["/bin/launchctl", "bootstrap"]:
            if self.bootstrap_fails:
                return 5, "Bootstrap failed: 5: Input/output error"
            self.loaded = True
            self.spawn("/opt/homebrew/opt/ollama/bin/ollama", daemon=True)
            return 0, ""
        raise AssertionError(f"unexpected command {argv}")

    def kill(self, pid: int, signum: int) -> None:
        self.signals.append((pid, signum))
        if pid not in self.procs:
            raise ProcessLookupError(pid)
        if signum == signal.SIGTERM and self.daemon_ignores_term:
            return
        self.procs.pop(pid)

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def now(self) -> float:
        return self.clock


def host_for(sv: ModuleType, fake: FakeHost) -> Any:
    config = sv.Config(
        label=LABEL, plist=Path(f"/Library/LaunchDaemons/{LABEL}.plist"), uid=UID, process="ollama"
    )
    return sv.Host(config, runner=fake.runner, kill=fake.kill, sleep=fake.sleep, clock=fake.now)


def receipt(sv: ModuleType, action: str) -> Any:
    return sv.Receipt(
        request_id="a" * 32,
        action=action,
        reason="test",
        supervisor_incarnation="i",
        label=LABEL,
        received_at=0.0,
    )


def runtime_pids(fake: FakeHost) -> set[int]:
    return {
        p for p, d in fake.procs.items() if d["uid"] == UID and d["command"].endswith("/ollama")
    }


def test_only_the_runtime_accounts_named_processes_are_in_scope(sv: ModuleType) -> None:
    fake = FakeHost()
    found = {p.pid for p in host_for(sv, fake).processes()}
    # The daemon and its runner; not root's syslogd, not the account's shell.
    assert found == runtime_pids(fake)
    assert len(found) == 2


def test_a_stop_unloads_the_job_and_leaves_no_runtime_process(sv: ModuleType) -> None:
    fake = FakeHost()
    done = sv.execute(host_for(sv, fake), receipt(sv, "stop"))

    assert done.result == "ok", done.error
    assert not fake.loaded
    assert runtime_pids(fake) == set()
    assert len(done.before) == 2
    assert done.after == []
    assert [s["step"] for s in done.steps] == ["bootout", "unloaded", "stopped"]
    assert fake.signals == []


def test_a_runner_that_outlives_the_bootout_is_signalled_by_identity(sv: ModuleType) -> None:
    fake = FakeHost()
    fake.runners_ignore_bootout = True
    runner = next(iter(runtime_pids(fake) - {fake.daemon}))

    done = sv.execute(host_for(sv, fake), receipt(sv, "stop"))

    assert done.result == "ok", done.error
    assert fake.signals == [(runner, signal.SIGTERM)]
    assert runtime_pids(fake) == set()


def test_a_reused_pid_is_never_signalled(sv: ModuleType) -> None:
    """The runner exits and its PID is reused by a different process before
    the signal: the identity no longer matches, so nothing is sent to it."""
    fake = FakeHost()
    fake.runners_ignore_bootout = True
    host = host_for(sv, fake)
    stale = next(p for p in host.processes() if p.pid != fake.daemon)
    fake.procs[stale.pid]["lstart"] = "Sun Oct 25 11:59:59 2026"

    assert host.signal(stale, signal.SIGTERM) is False
    assert fake.signals == []


def test_a_stop_that_cannot_end_the_runtime_fails_and_says_which(sv: ModuleType) -> None:
    fake = FakeHost()
    fake.runners_ignore_bootout = True
    fake.daemon_ignores_term = True
    survivor = next(iter(runtime_pids(fake) - {fake.daemon}))
    # SIGKILL always works on a real host; here it does not, to reach the check.
    fake.kill = lambda pid, signum: fake.signals.append((pid, signum))  # type: ignore[method-assign]

    done = sv.execute(host_for(sv, fake), receipt(sv, "stop"))

    assert done.result == "failed"
    assert str(survivor) in done.error
    assert [s for _, s in fake.signals] == [signal.SIGTERM, signal.SIGKILL]


def test_a_restart_produces_a_daemon_none_of_the_stopped_processes_was(sv: ModuleType) -> None:
    fake = FakeHost()
    old = runtime_pids(fake)

    done = sv.execute(host_for(sv, fake), receipt(sv, "restart"))

    assert done.result == "ok", done.error
    assert fake.loaded
    assert fake.daemon not in old
    assert done.job_after == {"loaded": True, "pid": fake.daemon}
    assert done.steps[-1]["step"] == "started"


def test_a_failed_bootstrap_is_a_failed_receipt(sv: ModuleType) -> None:
    fake = FakeHost()
    fake.bootstrap_fails = True

    done = sv.execute(host_for(sv, fake), receipt(sv, "restart"))

    assert done.result == "failed"
    assert "bootstrap" in done.error
    assert not fake.loaded


def test_starting_a_running_job_changes_nothing(sv: ModuleType) -> None:
    fake = FakeHost()
    daemon = fake.daemon

    done = sv.execute(host_for(sv, fake), receipt(sv, "start"))

    assert done.result == "ok", done.error
    assert fake.daemon == daemon
    assert [s["step"] for s in done.steps] == ["already_loaded", "started"]


# -- requests and receipts -------------------------------------------------


def write_request(directory: Path, request_id: str, **document: Any) -> Path:
    path = directory / f"{request_id}.json"
    path.write_text(json.dumps({"request_id": request_id, **document}))
    return path


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    requests, receipts = tmp_path / "requests", tmp_path / "receipts"
    requests.mkdir()
    receipts.mkdir()
    return requests, receipts


def test_a_request_runs_once_and_leaves_a_receipt(sv: ModuleType, dirs: tuple[Path, Path]) -> None:
    requests, receipts = dirs
    fake = FakeHost()
    host = host_for(sv, fake)
    write_request(requests, "b" * 32, action="restart", reason="reset")

    sv.cycle(host, requests, receipts, "inc")

    done = json.loads((receipts / f"{'b' * 32}.json").read_text())
    assert done["result"] == "ok"
    assert done["supervisor_incarnation"] == "inc"
    assert list(requests.iterdir()) == []

    # The same id again: discarded, never executed a second time.
    daemon = fake.daemon
    write_request(requests, "b" * 32, action="stop", reason="again")
    sv.cycle(host, requests, receipts, "inc")
    assert fake.loaded and fake.daemon == daemon
    assert json.loads((receipts / f"{'b' * 32}.json").read_text())["action"] == "restart"


@pytest.mark.parametrize(
    "document",
    [
        {"action": "rm -rf /", "reason": "x"},
        {"action": "stop", "reason": "x", "label": "com.apple.whatever"},
        {"action": "stop", "reason": "x" * 201},
        {"action": "stop", "reason": "line\nbreak"},
        {"action": "stop"},
    ],
)
def test_anything_but_a_well_formed_request_is_rejected_unexecuted(
    sv: ModuleType, dirs: tuple[Path, Path], document: dict[str, Any]
) -> None:
    requests, receipts = dirs
    fake = FakeHost()
    write_request(requests, "c" * 32, **document)

    sv.cycle(host_for(sv, fake), requests, receipts, "inc")

    done = json.loads((receipts / f"{'c' * 32}.json").read_text())
    assert done["result"] == "rejected"
    assert fake.loaded and fake.signals == []


def test_a_request_filed_under_another_id_is_rejected(
    sv: ModuleType, dirs: tuple[Path, Path]
) -> None:
    requests, receipts = dirs
    path = requests / f"{'d' * 32}.json"
    path.write_text(json.dumps({"request_id": "e" * 32, "action": "stop", "reason": "x"}))
    fake = FakeHost()

    sv.cycle(host_for(sv, fake), requests, receipts, "inc")

    assert json.loads((receipts / f"{'d' * 32}.json").read_text())["result"] == "rejected"
    assert fake.loaded


def test_a_link_in_the_requests_directory_is_not_followed(
    sv: ModuleType, dirs: tuple[Path, Path], tmp_path: Path
) -> None:
    requests, receipts = dirs
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"request_id": "f" * 32, "action": "stop", "reason": "x"}))
    os.symlink(target, requests / f"{'f' * 32}.json")
    fake = FakeHost()

    sv.cycle(host_for(sv, fake), requests, receipts, "inc")

    assert json.loads((receipts / f"{'f' * 32}.json").read_text())["result"] == "rejected"
    assert fake.loaded and target.exists()


def test_files_that_are_not_requests_are_left_alone(
    sv: ModuleType, dirs: tuple[Path, Path]
) -> None:
    requests, receipts = dirs
    (requests / ".staging.tmp").write_text("{}")
    (requests / "notes.txt").write_text("hello")

    sv.cycle(host_for(sv, FakeHost()), requests, receipts, "inc")

    assert sorted(p.name for p in requests.iterdir()) == [".staging.tmp", "notes.txt"]
    assert list(receipts.iterdir()) == []


def test_receipts_must_be_roots_alone(sv: ModuleType, tmp_path: Path) -> None:
    # A test runs unprivileged, so its own directory is never root's.
    assert sv.private_to_root(tmp_path) is False
