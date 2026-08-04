#!/usr/bin/env python3
"""Report what only the host knows, over loopback, for the management UI.

Why this exists at all. The backend runs in Docker, and on macOS that means a
Linux VM: a container reading /proc or `psutil` describes the VM's memory and
the VM's disk, not the Mac's. Those numbers look entirely plausible and are
wrong, which is worse than having none. This is the same constraint that keeps
the model runtimes off Docker (ARCHITECTURE.md 0.1), and it has the same shape
of answer — run natively, bind loopback, let containers in through
host.docker.internal.

**Scope is deliberately "is there room", not "how is it performing".** Free
memory, free disk, uptime, load. No GPU utilisation and no thermal state:
`powermetrics` needs root, and giving a launchd job root to draw a chart is a
trade worth making on purpose rather than as a side effect of this file. The
Ollama half of "what is loaded" is not here either, because the platform
already asks Ollama directly through its own API.

**No authentication, matching Ollama beside it.** The listener is bound to
127.0.0.1, so the boundary is the socket; anything on this host that could
reach it can already run `vm_stat`. Nothing here is a secret and nothing here
writes.

Stdlib only, and no venv: a launchd job that depends on a project's
virtualenv breaks the first time the project is rebuilt. /usr/bin/python3 is
the one interpreter macOS guarantees.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("NEXUS_HOST_METRICS_PORT", "9101"))
DATA_VOLUME = os.environ.get("NEXUS_HOST_METRICS_VOLUME", "/")


def _sysctl_int(name: str) -> int | None:
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=5
        )
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _memory() -> dict[str, float | None]:
    """Total and available memory in GB.

    "Available" is the interesting number and the one macOS does not report
    directly. It is derived the way Activity Monitor's own figure is: free
    pages plus the ones the kernel would reclaim without swapping — inactive
    and speculative — while *excluding* wired and compressed pages, which are
    not available at any price. Anonymous pages are excluded too: they belong
    to a running process and reclaiming them means swapping, which on a machine
    whose whole purpose is holding model weights is the state we are trying to
    stay out of rather than headroom to spend.
    """
    total_bytes = _sysctl_int("hw.memsize")
    page_size = _sysctl_int("hw.pagesize") or 4096

    stats: dict[str, int] = {}
    try:
        out = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            match = re.match(r'"?([^":]+)"?:\s+(\d+)\.', line)
            if match:
                stats[match.group(1).strip()] = int(match.group(2))
    except (OSError, subprocess.SubprocessError):
        pass

    available_pages = (
        stats.get("Pages free", 0)
        + stats.get("Pages inactive", 0)
        + stats.get("Pages speculative", 0)
    )
    gb = 1024**3
    return {
        "total_gb": round(total_bytes / gb, 2) if total_bytes else None,
        "available_gb": round(available_pages * page_size / gb, 2) if stats else None,
        # Reported rather than folded into "available": a machine swapping is in
        # a different state from one merely low, and the difference matters
        # before a model load rather than after it.
        "swap_used_gb": _swap_used_gb(),
    }


def _swap_used_gb() -> float | None:
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5
        )
        match = re.search(r"used\s*=\s*([\d.]+)([MG])", out.stdout)
        if not match:
            return None
        value = float(match.group(1))
        return round(value / 1024 if match.group(2) == "M" else value, 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _disk() -> dict[str, float | None]:
    """Free space where the weights live.

    Model files are the only thing on this machine that grows by gigabytes at a
    time, and the registry will happily start a download that cannot finish.
    """
    try:
        usage = shutil.disk_usage(DATA_VOLUME)
    except OSError:
        return {"total_gb": None, "free_gb": None}
    gb = 1024**3
    return {
        "volume": DATA_VOLUME,
        "total_gb": round(usage.total / gb, 2),
        "free_gb": round(usage.free / gb, 2),
    }


def _load() -> dict[str, float | int | None]:
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        one = five = fifteen = None
    return {
        "load_1m": round(one, 2) if one is not None else None,
        "load_5m": round(five, 2) if five is not None else None,
        "load_15m": round(fifteen, 2) if fifteen is not None else None,
        "cpu_count": os.cpu_count(),
        "uptime_seconds": _uptime_seconds(),
    }


def _uptime_seconds() -> int | None:
    boot = _sysctl_int("kern.boottime")
    if boot:
        return int(time.time()) - boot
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5
        )
        match = re.search(r"sec\s*=\s*(\d+)", out.stdout)
        return int(time.time()) - int(match.group(1)) if match else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def snapshot() -> dict[str, object]:
    return {"memory": _memory(), "disk": _disk(), "system": _load()}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        if self.path.rstrip("/") not in ("", "/host"):
            self.send_error(404)
            return
        body = json.dumps(snapshot()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence the per-request line.

        The backend polls this on a timer, so the default handler would write a
        log entry every few seconds forever — a file that grows without bound to
        record that nothing happened, which is the exact problem the retention
        work was about.
        """


def main() -> None:
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
