"""Asking the host's runtime supervisor to stop, start or restart the runtime.

The supervisor (`scripts/host/runtime_supervisor.py`, P3 on #61) runs as root on
the macOS host and reads requests from a directory this agent writes. It
answers each with a receipt in a directory the agent can only read. This side
writes a request, waits for its receipt, and checks that the receipt answers
that request; what the supervisor may act on is fixed on the host, not here.

A request that times out is withdrawn if the supervisor has not picked it up.
If it has, it may still run: the refusal says so and names the request, whose
receipt `receipt` can read later. A stop never happens without leaving one.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

ACTIONS = ("stop", "start", "restart")
_ID = re.compile(r"[0-9a-f]{32}")


class SupervisorRefused(Exception):  # noqa: N818 - a refusal, reported as such
    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


class Supervisor:
    def __init__(
        self,
        requests_dir: Path,
        receipts_dir: Path,
        *,
        timeout_s: float = 180.0,
        poll_s: float = 0.5,
    ) -> None:
        self._requests = requests_dir
        self._receipts = receipts_dir
        self._timeout = timeout_s
        self._poll = poll_s

    @property
    def available(self) -> bool:
        return self._requests.is_dir() and self._receipts.is_dir()

    async def run(
        self, action: str, reason: str, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """The supervisor's receipt for `action`, or `SupervisorRefused`.

        A caller that names the request (the maintenance coordinator, P4 on
        #61) can ask again after a timeout or a restart and get the same
        request's answer: an existing receipt is returned, and a request the
        supervisor already holds is waited for rather than written twice.
        """
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}")
        if request_id is not None and not _ID.fullmatch(request_id):
            raise ValueError("request_id must be 32 lowercase hex characters")
        if not self.available:
            raise SupervisorRefused("the runtime supervisor's directories are not mounted")
        request_id = request_id or secrets.token_hex(16)
        request = self._requests / f"{request_id}.json"
        existing = self.receipt(request_id)
        if existing is not None:
            return self._checked(existing, request_id, action)
        if not request.exists() and not (self._requests / f".{request_id}.claimed").exists():
            document = {"request_id": request_id, "action": action, "reason": reason[:200]}
            staging = self._requests / f".{request_id}.tmp"
            try:
                staging.write_text(json.dumps(document))
                os.replace(staging, request)
            except OSError as exc:
                raise SupervisorRefused(f"cannot write a supervisor request: {exc}") from exc
        claimed = self._requests / f".{request_id}.claimed"
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            receipt = self.receipt(request_id)
            if receipt is not None:
                return self._checked(receipt, request_id, action)
            if not request.exists() and not claimed.exists():
                # The supervisor renames before it runs and removes the claim
                # only after the receipt, so neither file and no receipt means
                # the agent withdrew it (`withdraw`): it will never run.
                receipt = self.receipt(request_id)
                if receipt is not None:
                    return self._checked(receipt, request_id, action)
                raise SupervisorRefused(
                    f"request {request_id} was withdrawn before the supervisor took it",
                    request_id=request_id,
                )
            await asyncio.sleep(self._poll)
        try:
            request.unlink()
        except FileNotFoundError:
            raise SupervisorRefused(
                f"the supervisor took request {request_id} but wrote no receipt in time; "
                "it may still run",
                request_id=request_id,
            ) from None
        except OSError:
            pass
        raise SupervisorRefused(
            f"the runtime supervisor did not answer; request {request_id} was withdrawn",
            request_id=request_id,
        )

    def outstanding(self) -> tuple[list[str], list[str]]:
        """Requests not yet answered: those the supervisor has not taken, and
        those it has taken and may be running now (review of #80)."""
        if not self.available:
            return [], []
        waiting, running = [], []
        for path in self._requests.iterdir():
            name = path.name
            if name.endswith(".json") and _ID.fullmatch(name.removesuffix(".json")):
                waiting.append(name.removesuffix(".json"))
            elif name.startswith(".") and name.endswith(".claimed"):
                request_id = name[1:].removesuffix(".claimed")
                if _ID.fullmatch(request_id) and self.receipt(request_id) is None:
                    running.append(request_id)
        return sorted(waiting), sorted(running)

    def withdraw(self, request_id: str) -> bool:
        """Remove a request the supervisor has not taken. False if it already
        has, in which case it may be running."""
        if not _ID.fullmatch(request_id):
            return False
        try:
            (self._requests / f"{request_id}.json").unlink()
        except FileNotFoundError:
            return False
        return True

    def receipt(self, request_id: str) -> dict[str, Any] | None:
        if not _ID.fullmatch(request_id):
            return None
        try:
            document = json.loads((self._receipts / f"{request_id}.json").read_text())
        except (OSError, ValueError):
            return None
        return document if isinstance(document, dict) else None

    @staticmethod
    def _checked(receipt: dict[str, Any], request_id: str, action: str) -> dict[str, Any]:
        if receipt.get("request_id") != request_id or receipt.get("action") != action:
            raise SupervisorRefused(
                f"the receipt for {request_id} does not answer this request: "
                f"{receipt.get('request_id')} {receipt.get('action')}",
                request_id=request_id,
            )
        return receipt
