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
    ) -> dict[str, Any]:
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
        started = time.monotonic()
        reply = self.client.post("/api/chat", json=body)
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
        "runtime_process": runtime_process(),
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


def runtime_process() -> dict[str, Any] | None:
    """The serving process's PID and start time, read from the host.

    The evidence the plan's "verified runtime reset" needs: a different start
    time is a restart; a request issued before it cannot still be running in
    it. Read with `ps`, so only meaningful when the probe runs on the runtime's
    own host. None anywhere else, rather than a guess.
    """
    try:
        pids = subprocess.run(  # noqa: S603 - fixed argv, no input
            ["/usr/bin/pgrep", "-f", "ollama serve"], capture_output=True, text=True, timeout=5
        ).stdout.split()
        if not pids:
            return None
        pid = pids[0]
        started = subprocess.run(  # noqa: S603 - argv is a PID pgrep printed
            ["/bin/ps", "-o", "lstart=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return {"pid": int(pid), "started": started, "host": os.uname().nodename}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def size_to_runtime_count(
    target: int,
    build: Callable[[int], Any],
    count: Callable[[Any], int],
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

    `count` must see the whole prompt. A runtime truncates prompts at its
    context, so size over-limit payloads against a larger context than the one
    under test.
    """
    base = count(build(0))
    lo_n, lo_c = 0, base
    best: tuple[Any, int] = (build(0), base)
    if lo_c >= target:
        return best
    hi: tuple[int, int] | None = None
    n = max(first_guess, 1)
    for _ in range(max_steps):
        payload = build(n)
        got = count(payload)
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
