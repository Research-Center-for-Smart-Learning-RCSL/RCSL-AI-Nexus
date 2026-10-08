"""Shared plumbing for the runtime probes (#24 PR0).

Every probe sends real requests to a live runtime and some load or unload
models, so every probe refuses to run without `--i-own-the-window`. Results are
JSON lines, each carrying the fingerprint that makes it comparable with a later
run: runtime version, model digests, the request's context and options. A table
in an issue is only as good as the conditions it was measured under, and the
2026-10-07 tables had to be reconstructed from scratch notes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_LOG = Path("/opt/homebrew/var/log/ollama.log")


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--ollama", default=DEFAULT_OLLAMA)
    p.add_argument("--ollama-log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--out", type=Path, help="append JSON lines here as well as to stdout")
    p.add_argument(
        "--i-own-the-window",
        action="store_true",
        help="required: these probes load models and occupy the runtime",
    )
    return p


def require_window(args: argparse.Namespace) -> None:
    if not args.i_own_the_window:
        sys.exit("refusing: this probe occupies the runtime; pass --i-own-the-window")


@dataclass
class Runtime:
    """The few Ollama calls the probes need, with nothing hidden."""

    client: httpx.Client

    def version(self) -> str:
        return str(self.client.get("/api/version").json()["version"])

    def digests(self) -> dict[str, str]:
        return {m["name"]: m["digest"][:12] for m in self.client.get("/api/tags").json()["models"]}

    def resident(self) -> list[dict[str, Any]]:
        return [
            {
                "name": m["name"],
                "size_gb": round(m["size"] / 2**30, 2),
                "context": m.get("context_length"),
            }
            for m in self.client.get("/api/ps").json()["models"]
        ]

    def load(self, model: str, num_ctx: int) -> float:
        started = time.monotonic()
        self.client.post(
            "/api/generate",
            json={"model": model, "prompt": "", "keep_alive": -1, "options": {"num_ctx": num_ctx}},
        ).raise_for_status()
        return round(time.monotonic() - started, 2)

    def load_embedder(self, model: str, num_ctx: int) -> None:
        self.client.post(
            "/api/embed",
            json={
                "model": model,
                "input": ["warmup"],
                "keep_alive": -1,
                "options": {"num_ctx": num_ctx},
            },
        ).raise_for_status()

    def unload(self, model: str) -> None:
        self.client.post("/api/generate", json={"model": model, "keep_alive": 0}).raise_for_status()

    def chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        num_ctx: int,
        *,
        num_predict: int = 1,
        tools: Sequence[dict[str, Any]] | None = None,
        truncate: bool | None = None,
    ) -> dict[str, Any] | None:
        """One non-streaming chat. With `truncate=False` the runtime refuses a
        prompt that does not fit instead of shortening it; that refusal returns
        None, never a count, so a caller cannot mistake it for one."""
        body: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": 0,
                "seed": 1,
            },
        }
        if tools:
            body["tools"] = list(tools)
        if truncate is not None:
            body["truncate"] = truncate
        started = time.monotonic()
        reply = self.client.post("/api/chat", json=body)
        if reply.status_code == 400 and "exceed_context" in reply.text:
            return None
        reply.raise_for_status()
        data = reply.json()
        return {
            "wall_s": round(time.monotonic() - started, 3),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "prompt_eval_s": round(data.get("prompt_eval_duration", 0) / 1e9, 3),
            "eval_count": data.get("eval_count"),
            "eval_s": round(data.get("eval_duration", 0) / 1e9, 3),
            "load_s": round(data.get("load_duration", 0) / 1e9, 3),
            "done_reason": data.get("done_reason"),
        }


@contextmanager
def runtime(args: argparse.Namespace) -> Iterator[Runtime]:
    with httpx.Client(base_url=args.ollama, timeout=1800) as client:
        yield Runtime(client)


class Recorder:
    """JSON lines to stdout and, optionally, a file; one fingerprint per run."""

    def __init__(self, probe: str, out: Path | None, fingerprint: dict[str, Any]) -> None:
        self._probe = probe
        self._sinks: list[TextIO] = [sys.stdout]
        if out is not None:
            self._sinks.append(out.open("a"))
        self.emit("fingerprint", **fingerprint)

    def emit(self, kind: str, **fields: Any) -> None:
        line = json.dumps(
            {
                "probe": self._probe,
                "kind": kind,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                **fields,
            },
            ensure_ascii=False,
        )
        for sink in self._sinks:
            sink.write(line + "\n")
            sink.flush()


def fingerprint(rt: Runtime, models: Sequence[str]) -> dict[str, Any]:
    digests = rt.digests()
    return {
        "runtime": "ollama",
        "version": rt.version(),
        "digests": {m: digests.get(m) for m in models},
        "resident": rt.resident(),
        "runtime_process": runtime_process(str(rt.client.base_url)),
    }


class LogTail:
    """The runtime's log since a mark, for evidence the API does not return.

    Truncation, context shifts and scheduler predictions are only in the log, so
    a probe that reports them has to read it; `lines()` returns what was written
    after `mark()`, filtered to the lines a probe cares about.
    """

    INTERESTING = re.compile(
        r"truncat|shift|predicted|evict|loading model|cache hit|cache miss|"
        r"stop processing|cancel|n_ctx_slot|started in",
        re.IGNORECASE,
    )

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0

    def mark(self) -> None:
        self._offset = self._path.stat().st_size if self._path.exists() else 0

    def lines(self) -> list[str]:
        if not self._path.exists():
            return []
        with self._path.open("rb") as handle:
            handle.seek(self._offset)
            text = handle.read().decode(errors="replace")
        return [
            line[:300]
            for line in text.splitlines()
            if "[GIN]" not in line and self.INTERESTING.search(line)
        ]


def runtime_process(endpoint: str) -> dict[str, Any]:
    """The process serving `endpoint`, identified by the socket it listens on.

    The evidence the spec's "verified runtime reset" needs (#24 §3): a changed
    PID or start time **of the process that owns the endpoint's listening
    socket** is a restart of that endpoint. Matching processes by name could
    pick an unrelated one, or the first of several (review on #26), so the
    owner is read from `netstat -anv`, which names the PID listening on each
    socket and, unlike `lsof`, sees sockets of other users without root.

    Only an endpoint on this host's loopback can be tied to a local process.
    Anything else, no listener, or more than one is `inconclusive`, never a
    guess.
    """
    url = urlsplit(endpoint)
    host, port = url.hostname or "", url.port or 80
    if host not in ("127.0.0.1", "localhost", "::1"):
        return {"status": "inconclusive", "reason": f"{host} is not this host's loopback"}
    try:
        table = subprocess.run(  # noqa: S603 - fixed argv, no input
            ["/usr/sbin/netstat", "-anv", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "inconclusive", "reason": f"netstat failed: {exc}"}
    owners = set()
    for line in table.splitlines():
        fields = line.split()
        if len(fields) > 5 and "LISTEN" in fields and fields[3].endswith(f".{port}"):
            owner = next((f for f in fields if re.fullmatch(r"[^:\s]+:\d+", f)), None)
            if owner:
                owners.add(owner)
    if len(owners) != 1:
        return {
            "status": "inconclusive",
            "reason": f"{len(owners)} listeners on port {port}: {sorted(owners)}",
        }
    name, _, pid = next(iter(owners)).rpartition(":")
    try:
        detail = subprocess.run(  # noqa: S603 - argv is a PID netstat printed
            ["/bin/ps", "-o", "user=,lstart=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.split(maxsplit=1)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"status": "inconclusive", "reason": f"ps failed: {exc}"}
    if len(detail) != 2:
        return {"status": "inconclusive", "reason": f"process {pid} vanished"}
    return {
        "status": "bound",
        "endpoint": f"{host}:{port}",
        "process": name,
        "pid": int(pid),
        "user": detail[0],
        "started": detail[1].strip(),
        "host": os.uname().nodename,
    }


def size_to_runtime_count(
    target: int,
    build: Callable[[int], Any],
    count: Callable[[Any], int | None],
    *,
    first_guess: int,
    max_steps: int = 16,
) -> tuple[Any, int]:
    """Find a payload whose runtime token count is `target`, or the nearest below.

    `build(n)` makes a payload from a size knob (characters of filler) and
    `count(payload)` asks the runtime. Counts rise with the knob but not
    linearly, and one character can move them by more than one token, so this
    brackets the target and interpolates, settling on the largest count not
    above it. It never claims an exact hit it did not get: callers record the
    count returned, not the target.

    `count` must see the whole prompt or say it could not: it returns None when
    the runtime refused the payload as too large (`truncate: false`), which
    the search treats as an overshoot with no count. A count the runtime
    produced by shortening the prompt must never reach this function, which is
    why sizing requests carry `truncate: false` (review on #26).
    """
    first = count(build(0))
    if first is None:
        raise ValueError("the empty payload does not fit the sizing context")
    base = first
    lo_n, lo_c = 0, base
    best: tuple[Any, int] = (build(0), base)
    if lo_c >= target:
        return best
    hi: tuple[int, int] | None = None
    n = max(first_guess, 1)
    for _ in range(max_steps):
        payload = build(n)
        counted = count(payload)
        if counted is None:
            # Refused as too large: above the target, count unknown. Bracket it
            # without a count and bisect towards the last value that fitted.
            hi = (n, target + 1)
            if hi[0] - lo_n <= 1:
                break
            n = lo_n + max(1, (hi[0] - lo_n) // 2)
            continue
        got = counted
        if got == target:
            return payload, got
        if got < target:
            lo_n, lo_c = n, got
            if got > best[1]:
                best = (payload, got)
        else:
            hi = (n, got)
        if hi is not None and hi[0] - lo_n <= 1:
            break
        if hi is None:
            rate = (lo_c - base) / lo_n if lo_n else 1.0
            n = lo_n + max(1, round((target - lo_c) / max(rate, 1e-6)))
        else:
            fraction = (target - lo_c) / max(hi[1] - lo_c, 1)
            n = lo_n + max(1, min(hi[0] - lo_n - 1, round(fraction * (hi[0] - lo_n))))
    return best


def prefix_counts_are_complete(prefix_counts: Sequence[int], full_count: int) -> bool:
    """Whether the runtime's prefix counts rise strictly: a diagnostic only.

    `prefix_counts[k]` is the runtime's count for the first `k + 1` messages
    and `full_count` its count for all of them. A fall exposes lost content,
    but a rise does not prove its absence: the runtime drops *leading*
    messages and keeps the last, so a long final message can still out-count
    every prefix after earlier messages were removed (review on #24). The
    certificate is the runtime accepting the request with `truncate: false`.
    """
    sequence = [*prefix_counts, full_count]
    return len(sequence) >= 2 and all(a < b for a, b in zip(sequence, sequence[1:], strict=False))


def answered(result: dict[str, Any] | None) -> dict[str, Any]:
    """A chat result from a request that could not be refused (default truncation)."""
    if result is None:
        raise RuntimeError("the runtime refused a request sent without truncate=false")
    return result


def server_num_parallel(log_path: Path) -> str | None:
    """`OLLAMA_NUM_PARALLEL` as the server printed it at its last start."""
    if not log_path.exists():
        return None
    with log_path.open("rb") as handle:
        handle.seek(max(0, log_path.stat().st_size - 50_000_000))
        text = handle.read().decode(errors="replace")
    starts = [line for line in text.splitlines() if 'msg="server config"' in line]
    if not starts:
        return None
    match = re.search(r"OLLAMA_NUM_PARALLEL:(\S+)", starts[-1])
    return match.group(1) if match else None
