#!/usr/bin/env python3
"""Host-side witness of which runtime process serves an endpoint.

    sudo /usr/bin/python3 scripts/host/runtime_witness.py \
        --endpoint http://127.0.0.1:11434 \
        --out /Users/Shared/rcsl-witness/out --challenge /Users/Shared/rcsl-witness/challenge

Run by a root-owned launchd job on the runtime host (design S4 and T1 on #24,
approved by the maintainer). Nothing inside a container can see the macOS
host's processes, so this process observes the runtime for the node agent and
publishes what it saw. It has no network access and writes one file.

Each cycle, in this order:

1. Read the challenge file, if any: a nonce of 32 hex characters written by a
   resolver that already holds the node's host lock. Anything else in the file
   is ignored; the content is never interpreted beyond that format.
2. **Then** observe the process that owns the endpoint's listening socket:
   its PID and start time, by the same `netstat`/`ps` method as
   `scripts/runtime-probes/_common.py`. Reading the challenge before observing
   is what makes an attestation carrying nonce N an observation taken after N
   was issued, which the ordered reset evidence depends on (design T1).
3. Publish `{nonce, witness_incarnation, seq, pid, start_time, endpoint,
   observed_at}` atomically. `witness_incarnation` is random per start of this
   process; `seq` increases by one per publication within an incarnation.

`--out` is mounted read-only into the agent's containers and `--challenge`
read-write; nothing in a container can write an attestation. Standard library
only, so the job needs nothing installed on the host.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CHALLENGE_FILE = "challenge"
ATTESTATION_FILE = "attestation.json"
_NONCE = re.compile(r"[0-9a-f]{32}")


def read_challenge(directory: Path) -> str | None:
    try:
        raw = (directory / CHALLENGE_FILE).read_text(encoding="ascii", errors="strict").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return raw if _NONCE.fullmatch(raw) else None


def listener_owner(netstat_output: str, host: str, port: int) -> tuple[str, ...]:
    """The `name:pid` owners of listening sockets that can serve host:port.

    The same local address, or a wildcard of a compatible family; a listener
    on another address with the same port is not this endpoint's.
    """
    families = {"127.0.0.1": ("tcp4", "tcp46"), "::1": ("tcp6", "tcp46")}
    addresses = ("127.0.0.1", "::1") if host == "localhost" else (host,)
    owners: set[str] = set()
    for line in netstat_output.splitlines():
        fields = line.split()
        if len(fields) <= 5 or "LISTEN" not in fields:
            continue
        proto, local = fields[0], fields[3]
        address, _, local_port = local.rpartition(".")
        if local_port != str(port):
            continue
        if any(proto in families.get(a, ()) and address in (a, "*") for a in addresses):
            owner = next((f for f in fields if re.fullmatch(r"[^:\s]+:\d+", f)), None)
            if owner:
                owners.add(owner)
    return tuple(sorted(owners))


def observe(endpoint: str) -> dict[str, Any]:
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
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "inconclusive", "reason": f"netstat failed: {exc}"}
    owners = listener_owner(table, host, port)
    if len(owners) != 1:
        return {"status": "inconclusive", "reason": f"{len(owners)} listeners: {list(owners)}"}
    name, _, pid = owners[0].rpartition(":")
    try:
        started = subprocess.run(  # noqa: S603 - argv is a PID netstat printed
            ["/bin/ps", "-o", "lstart=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"status": "inconclusive", "reason": f"ps failed: {exc}"}
    if not started:
        return {"status": "inconclusive", "reason": f"pid {pid} vanished"}
    return {"status": "observed", "process": name, "pid": int(pid), "start_time": started}


def publish(directory: Path, document: dict[str, Any]) -> None:
    staging = directory / f".{ATTESTATION_FILE}.{os.getpid()}"
    staging.write_text(json.dumps(document, sort_keys=True))
    os.chmod(staging, 0o644)
    os.replace(staging, directory / ATTESTATION_FILE)


def cycle(endpoint: str, out: Path, challenge: Path, incarnation: str, seq: int) -> None:
    nonce = read_challenge(challenge)  # first: the observation must postdate it
    seen = observe(endpoint)
    publish(
        out,
        {
            "nonce": nonce,
            "witness_incarnation": incarnation,
            "seq": seq,
            "endpoint": f"{urlsplit(endpoint).hostname}:{urlsplit(endpoint).port}",
            "observed_at": time.time(),
            **seen,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--challenge", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    for directory in (args.out, args.challenge):
        if not directory.is_dir():
            print(f"{directory} is not a directory", file=sys.stderr)
            return 1

    incarnation = secrets.token_hex(16)
    seq = 0
    while True:
        seq += 1
        try:
            cycle(args.endpoint, args.out, args.challenge, incarnation, seq)
        except OSError as exc:
            print(f"publication failed: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
