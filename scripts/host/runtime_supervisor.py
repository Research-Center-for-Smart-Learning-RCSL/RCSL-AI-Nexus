#!/usr/bin/env python3
"""Host-side supervisor that stops, starts and restarts the native runtime.

    sudo /usr/bin/python3 -I scripts/host/runtime_supervisor.py \
        --label online.rcsl.ollama --plist /Library/LaunchDaemons/online.rcsl.ollama.plist \
        --user _rcslollama --process ollama --process llama-server \
        --requests <dir> --receipts <dir>

Run by a root-owned launchd job on the runtime host (P3 on #61, chosen by the
maintainer on 2026-10-24 over a manual restart). The node agent runs in a Linux
VM and cannot control this Mac's processes, so a maintenance entry or a reset
asks this process to do it, through files, the way the agent already asks the
runtime witness for an observation. It has no network access.

**What it will do is fixed here and on its command line, never by a request.**
A request names one of three actions, `stop`, `start` or `restart`, and a
request id; the launchd label, the plist, the runtime's account and the
process names come from the arguments launchd starts it with. There is no
shell, no caller-supplied PID, path or label, and nothing a request says is
executed or interpreted beyond those fields.

`stop` unloads the job with `launchctl bootout`, so launchd's `KeepAlive`
cannot respawn it during cleanup, then waits for every process the runtime's
account runs under those names, the daemon and its model runners alike,
to exit. One that outlives the wait is sent SIGTERM and then SIGKILL, each
only after its birth identity (PID and start time) is read again and found
unchanged, so a reused PID is never signalled. The stop succeeds only on a
fresh scan that finds no such process and a job that is no longer loaded.
`start` bootstraps the plist and waits for launchd to report the daemon's
PID. `restart` is a stop, then a start that must produce a daemon whose
identity none of the stopped processes had.

Each request is executed at most once: it is claimed by renaming before it
runs, so the agent can withdraw one only before it is taken. Its receipt, written atomically to
`--receipts` under the request's id, records the processes before and after,
every step and the result, and a request whose receipt exists is discarded
unexecuted. `--receipts` must be root's alone; the agent mounts it read-only,
and it writes only `--requests`. Standard library only, so the job needs
nothing installed on the host.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ACTIONS = ("stop", "start", "restart")
REQUEST_SUFFIX = ".json"
REQUEST_MAX_BYTES = 4096
REASON_MAX = 200
_ID = re.compile(r"[0-9a-f]{32}")
_JOB_PID = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    uid: int
    started: str
    command: str

    @property
    def identity(self) -> tuple[int, str]:
        return (self.pid, self.started)


@dataclass(frozen=True)
class Config:
    label: str
    plist: Path
    uid: int
    processes: tuple[str, ...]
    unload_timeout_s: float = 30.0
    exit_timeout_s: float = 20.0
    signal_timeout_s: float = 10.0
    start_timeout_s: float = 30.0
    poll_s: float = 0.5


Runner = Callable[[Sequence[str]], tuple[int, str]]


def run(argv: Sequence[str]) -> tuple[int, str]:
    """A fixed argv, never a shell; output is for parsing and the receipt."""
    try:
        done = subprocess.run(  # noqa: S603 - argv is built here from fixed parts
            list(argv), capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return done.returncode, done.stdout + done.stderr


def parse_ps(output: str) -> list[Proc]:
    """Rows of `ps -axww -o pid=,ppid=,uid=,lstart=,comm=`.

    `lstart` is five fields (`Thu Oct  8 10:00:00 2026`); the command is the
    rest of the line and may contain spaces.
    """
    found: list[Proc] = []
    for line in output.splitlines():
        fields = line.split(None, 8)
        if len(fields) < 9:
            continue
        try:
            pid, ppid, uid = int(fields[0]), int(fields[1]), int(fields[2])
        except ValueError:
            continue
        found.append(Proc(pid, ppid, uid, " ".join(fields[3:8]), fields[8].strip()))
    return found


class Host:
    """The host as this supervisor sees it: processes, launchd and signals."""

    def __init__(
        self,
        config: Config,
        *,
        runner: Runner = run,
        kill: Callable[[int, int], None] = os.kill,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._run = runner
        self._kill = kill
        self.sleep = sleep
        self.clock = clock

    def processes(self) -> list[Proc]:
        """The runtime's processes: the configured account and process names."""
        code, output = self._run(["/bin/ps", "-axww", "-o", "pid=,ppid=,uid=,lstart=,comm="])
        if code != 0:
            raise SupervisorError(f"ps failed ({code}): {output.strip()[:200]}")
        return [
            p
            for p in parse_ps(output)
            if p.uid == self.config.uid and os.path.basename(p.command) in self.config.processes
        ]

    def job(self) -> dict[str, Any]:
        """Whether launchd has the job loaded, and the PID it reports."""
        code, output = self._run(["/bin/launchctl", "print", f"system/{self.config.label}"])
        if code != 0:
            return {"loaded": False, "pid": None}
        match = _JOB_PID.search(output)
        return {"loaded": True, "pid": int(match.group(1)) if match else None}

    def launchctl(self, *args: str) -> tuple[int, str]:
        return self._run(["/bin/launchctl", *args])

    def signal(self, target: Proc, signum: int) -> bool:
        """Signal `target` only if a fresh scan still shows the same birth identity."""
        if target.identity not in {p.identity for p in self.processes()}:
            return False
        try:
            self._kill(target.pid, signum)
        except ProcessLookupError:
            return False
        return True


class SupervisorError(Exception):
    pass


@dataclass
class Receipt:
    request_id: str
    action: str
    reason: str
    supervisor_incarnation: str
    label: str
    received_at: float
    finished_at: float | None = None
    result: str = "failed"
    error: str | None = None
    job_before: dict[str, Any] | None = None
    job_after: dict[str, Any] | None = None
    before: list[dict[str, Any]] = field(default_factory=list)
    after: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)

    def step(self, name: str, **detail: Any) -> None:
        self.steps.append({"at": time.time(), "step": name, **detail})


def _alive(host: Host, wanted: set[tuple[int, str]]) -> list[Proc]:
    return [p for p in host.processes() if p.identity in wanted]


def _wait(host: Host, timeout_s: float, done: Callable[[], bool]) -> bool:
    deadline = host.clock() + timeout_s
    while True:
        if done():
            return True
        if host.clock() >= deadline:
            return False
        host.sleep(host.config.poll_s)


def stop(host: Host, receipt: Receipt) -> None:
    config = host.config
    before = host.processes()
    wanted = {p.identity for p in before}
    code, output = host.launchctl("bootout", f"system/{config.label}")
    receipt.step("bootout", code=code, output=output.strip()[:500])
    if not _wait(host, config.unload_timeout_s, lambda: not host.job()["loaded"]):
        raise SupervisorError(f"{config.label} is still loaded after bootout")
    receipt.step("unloaded")
    if not _wait(host, config.exit_timeout_s, lambda: not _alive(host, wanted)):
        for signum, name in ((signal.SIGTERM, "SIGTERM"), (signal.SIGKILL, "SIGKILL")):
            remaining = _alive(host, wanted)
            if not remaining:
                break
            sent = [p.pid for p in remaining if host.signal(p, signum)]
            receipt.step(name, pids=sent)
            _wait(host, config.signal_timeout_s, lambda: not _alive(host, wanted))
    # A fresh scan, not the list taken before: a runner spawned during the stop
    # is as much the runtime as one that was already there.
    survivors = host.processes()
    if survivors:
        receipt.after = [asdict(p) for p in survivors]
        raise SupervisorError(f"runtime processes survived the stop: {[p.pid for p in survivors]}")
    if host.job()["loaded"]:
        raise SupervisorError(f"{config.label} was loaded again during the stop")
    receipt.step("stopped")


def start(host: Host, receipt: Receipt, *, not_one_of: set[tuple[int, str]]) -> None:
    config = host.config
    job = host.job()
    if not job["loaded"]:
        code, output = host.launchctl("bootstrap", "system", str(config.plist))
        receipt.step("bootstrap", code=code, output=output.strip()[:500])
        if code != 0:
            raise SupervisorError(f"bootstrap of {config.label} failed ({code})")
    else:
        receipt.step("already_loaded", pid=job["pid"])
    daemon: list[Proc] = []

    def running() -> bool:
        pid = host.job()["pid"]
        daemon[:] = [p for p in host.processes() if p.pid == pid]
        return bool(daemon)

    if not _wait(host, config.start_timeout_s, running):
        raise SupervisorError(f"{config.label} reported no running daemon after bootstrap")
    if daemon[0].identity in not_one_of:
        raise SupervisorError(f"the daemon {daemon[0].pid} is one the stop should have ended")
    receipt.step("started", pid=daemon[0].pid, started=daemon[0].started)


def execute(host: Host, receipt: Receipt) -> Receipt:
    try:
        receipt.job_before = host.job()
        before = host.processes()
        receipt.before = [asdict(p) for p in before]
        if receipt.action in ("stop", "restart"):
            stop(host, receipt)
        if receipt.action in ("start", "restart"):
            # Only a restart must produce a new daemon; a start of a running
            # job is a no-op that reports the daemon it found.
            stopped = {p.identity for p in before} if receipt.action == "restart" else set()
            start(host, receipt, not_one_of=stopped)
        receipt.after = [asdict(p) for p in host.processes()]
        receipt.job_after = host.job()
        receipt.result = "ok"
    except SupervisorError as exc:
        receipt.error = str(exc)
    except Exception as exc:  # noqa: BLE001 - recorded, and the loop goes on
        receipt.error = f"{type(exc).__name__}: {exc}"
    finally:
        receipt.finished_at = time.time()
    return receipt


def read_request(path: Path, request_id: str) -> dict[str, Any]:
    """The request at `path`, filed as `request_id`, or `ValueError`.

    Never follows a link: the directory is writable by the agent's account.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular file")
        raw = os.read(fd, REQUEST_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > REQUEST_MAX_BYTES:
        raise ValueError("request too large")
    document = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(document, dict) or set(document) != {"request_id", "action", "reason"}:
        raise ValueError("a request has exactly request_id, action and reason")
    action, reason = document["action"], document["reason"]
    if document["request_id"] != request_id:
        raise ValueError("request_id does not match the file name")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    if not isinstance(reason, str) or len(reason) > REASON_MAX or not reason.isprintable():
        raise ValueError("reason must be printable text of at most 200 characters")
    return document


def publish(directory: Path, receipt: Receipt) -> None:
    staging = directory / f".{receipt.request_id}.{os.getpid()}"
    staging.write_text(json.dumps(asdict(receipt), sort_keys=True))
    os.chmod(staging, 0o644)
    os.replace(staging, directory / f"{receipt.request_id}{REQUEST_SUFFIX}")


def pending(requests: Path) -> list[Path]:
    found = []
    for path in requests.iterdir():
        stem = path.name.removesuffix(REQUEST_SUFFIX)
        if path.name.endswith(REQUEST_SUFFIX) and _ID.fullmatch(stem):
            found.append(path)
    return sorted(found, key=lambda p: p.lstat().st_mtime)


def cycle(host: Host, requests: Path, receipts: Path, incarnation: str) -> None:
    """Handle every pending request, oldest first, one at a time.

    A request is claimed by renaming it before anything runs, so the agent can
    tell a withdrawn request (its unlink succeeded) from one already taken
    (the file is gone), and never withdraws one that is executing.
    """
    for path in pending(requests):
        request_id = path.name.removesuffix(REQUEST_SUFFIX)
        if (receipts / path.name).exists():
            path.unlink(missing_ok=True)  # executed already; never twice
            continue
        claimed = requests / f".{request_id}.claimed"
        try:
            os.rename(path, claimed)
        except FileNotFoundError:
            continue  # withdrawn by the agent before it was taken
        receipt = Receipt(
            request_id=request_id,
            action="",
            reason="",
            supervisor_incarnation=incarnation,
            label=host.config.label,
            received_at=time.time(),
        )
        try:
            document = read_request(claimed, request_id)
        except (OSError, ValueError) as exc:
            receipt.result = "rejected"
            receipt.error = str(exc)[:REASON_MAX]
            receipt.finished_at = time.time()
        else:
            receipt.action = document["action"]
            receipt.reason = document["reason"]
            execute(host, receipt)
        publish(receipts, receipt)
        claimed.unlink(missing_ok=True)


def private_to_root(directory: Path) -> bool:
    """Owned by root and writable by nobody else, so no receipt can be forged."""
    info = directory.stat()
    return info.st_uid == 0 and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--plist", type=Path, required=True)
    parser.add_argument("--user", required=True)
    # Repeated: the daemon and its model runners need not share a name. Ollama
    # 0.40 runs each model in a `llama-server`, not in another `ollama`.
    parser.add_argument("--process", action="append", required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    for directory in (args.requests, args.receipts):
        if not directory.is_dir():
            print(f"{directory} is not a directory", file=sys.stderr)
            return 1
    if not private_to_root(args.receipts):
        print(f"{args.receipts} must be owned by root and writable by root alone", file=sys.stderr)
        return 1
    try:
        uid = pwd.getpwnam(args.user).pw_uid
    except KeyError:
        print(f"no account named {args.user}", file=sys.stderr)
        return 1
    if uid == 0:
        print("the runtime's account must not be root", file=sys.stderr)
        return 1
    host = Host(Config(label=args.label, plist=args.plist, uid=uid, processes=tuple(args.process)))

    incarnation = secrets.token_hex(16)
    while True:
        try:
            cycle(host, args.requests, args.receipts, incarnation)
        except OSError as exc:
            print(f"cycle failed: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
