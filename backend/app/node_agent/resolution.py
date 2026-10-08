"""Clearing an `outcome_unknown` operation with ordered reset evidence.

The maintainer's decision on #24 (Q1, tightened by R1 and S4): a block is
cleared only by an audited resolution, and only on evidence that the runtime
instance that may have received the operation is gone, gathered in this order
(design S1, T1, U1):

1. **The sender is gone.** For an operation sent by an earlier agent, this
   agent's host lock proves it: the lock is only obtainable once every earlier
   holder in the domain has exited. For one this agent sent, its relay task
   has ended and the process holds no task for it.
2. **This agent's own admitted work is drained**, so the restart cannot cut
   off one of its tasks and make a new unknown.
3. **Baseline.** A fresh nonce is written to the witness's challenge file and
   the witness's answer to *that* nonce is the baseline `O1`: an observation
   produced after steps 1 and 2.
4. The operator restarts the runtime.
5. **After.** A second fresh nonce, answered by the same witness incarnation,
   must show a different `(pid, start_time)` from `O1`. A different
   incarnation means the witness itself restarted; the resolution starts over.

Elapsed time, lease expiry, an unanswered challenge, residency or the runtime
answering are never evidence. Until the witness has been installed and
validated on the host, `attest` cannot be answered and no block can be
cleared, which is the accepted state of 4a-1.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.node_agent.dispatch import Dispatcher
from app.node_agent.store import OperationStore

CHALLENGE_FILE = "challenge"
ATTESTATION_FILE = "attestation.json"


class ResolutionRefused(Exception):  # noqa: N818 - a refusal, reported as such
    pass


@dataclass(frozen=True, slots=True)
class Attestation:
    nonce: str
    incarnation: str
    seq: int
    pid: int
    start_time: str
    endpoint: str

    @property
    def instance(self) -> tuple[int, str]:
        return (self.pid, self.start_time)


class Witness:
    def __init__(
        self,
        out_dir: Path,
        challenge_dir: Path,
        *,
        expected_endpoint: str,
        timeout_s: float = 30.0,
        poll_s: float = 0.5,
    ) -> None:
        self._out = out_dir
        self._challenge = challenge_dir
        self._endpoint = expected_endpoint
        self._timeout = timeout_s
        self._poll = poll_s

    async def attest(self) -> Attestation:
        """The witness's answer to a nonce issued now, or `ResolutionRefused`."""
        nonce = secrets.token_hex(16)
        staging = self._challenge / f".{CHALLENGE_FILE}.{os.getpid()}"
        try:
            staging.write_text(nonce)
            os.replace(staging, self._challenge / CHALLENGE_FILE)
        except OSError as exc:
            raise ResolutionRefused(f"cannot issue a witness challenge: {exc}") from exc
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            document = self._read()
            if document is not None and document.get("nonce") == nonce:
                return self._attestation(document, nonce)
            await asyncio.sleep(self._poll)
        raise ResolutionRefused(
            "the runtime witness did not answer the challenge; reset evidence is unavailable"
        )

    def _read(self) -> dict[str, Any] | None:
        try:
            document = json.loads((self._out / ATTESTATION_FILE).read_text())
        except (OSError, ValueError):
            return None
        return document if isinstance(document, dict) else None

    def _attestation(self, document: dict[str, Any], nonce: str) -> Attestation:
        if document.get("status") != "observed":
            raise ResolutionRefused(f"the witness could not observe the runtime: {document}")
        if document.get("endpoint") != self._endpoint:
            raise ResolutionRefused(
                f"the witness observes {document.get('endpoint')}, not {self._endpoint}"
            )
        try:
            return Attestation(
                nonce=nonce,
                incarnation=str(document["witness_incarnation"]),
                seq=int(document["seq"]),
                pid=int(document["pid"]),
                start_time=str(document["start_time"]),
                endpoint=str(document["endpoint"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResolutionRefused(f"the witness document is malformed: {exc}") from exc


@dataclass
class _Pending:
    op_id: str
    evidence: str
    operator: str
    baseline: Attestation


class Resolutions:
    def __init__(self, dispatcher: Dispatcher, store: OperationStore, witness: Witness) -> None:
        self._dispatcher = dispatcher
        self._store = store
        self._witness = witness
        self._pending: dict[str, _Pending] = {}

    async def start(self, op_id: str, *, evidence: str, operator: str) -> dict[str, Any]:
        if not evidence.strip() or not operator.strip():
            raise ResolutionRefused("an operator and an evidence statement are required")
        operation = await self._store.observe(op_id)
        if operation is None or operation.state != "outcome_unknown":
            raise ResolutionRefused(f"{op_id} is not an unknown operation on this node")
        if self._dispatcher.holds(op_id):
            raise ResolutionRefused(f"{op_id} still has a task in this agent")
        sender_gone = (
            "earlier agent; this agent holds the host lock"
            if operation.origin_boot_id != self._store.ownership.boot_id
            else "this agent; its task for the operation has ended"
        )
        await self._dispatcher.drain()
        baseline = await self._witness.attest()
        resolution_id = uuid.uuid4().hex
        self._pending[resolution_id] = _Pending(op_id, evidence, operator, baseline)
        await self._store.audit(
            "resolution_baseline",
            op_id,
            {
                "resolution_id": resolution_id,
                "operator": operator,
                "sender": sender_gone,
                "baseline": asdict(baseline),
            },
        )
        return {
            "resolution_id": resolution_id,
            "op_id": op_id,
            "baseline": asdict(baseline),
            "next": "restart the runtime, then complete this resolution",
        }

    async def complete(self, resolution_id: str) -> dict[str, Any]:
        pending = self._pending.get(resolution_id)
        if pending is None:
            raise ResolutionRefused(f"no resolution {resolution_id} is in progress here")
        after = await self._witness.attest()
        if after.incarnation != pending.baseline.incarnation:
            del self._pending[resolution_id]
            raise ResolutionRefused(
                "the witness restarted since the baseline; start the resolution again"
            )
        if after.seq <= pending.baseline.seq or after.instance == pending.baseline.instance:
            raise ResolutionRefused(
                "the runtime has not restarted since the baseline "
                f"(pid {after.pid}, started {after.start_time})"
            )
        evidence = {
            "resolution_id": resolution_id,
            "operator": pending.operator,
            "statement": pending.evidence,
            "baseline": asdict(pending.baseline),
            "after": asdict(after),
            "resolver_generation": self._store.ownership.generation,
            "resolver_boot_id": self._store.ownership.boot_id,
        }
        if not await self._store.resolve_unknown(pending.op_id, evidence):
            del self._pending[resolution_id]
            raise ResolutionRefused(f"{pending.op_id} is no longer unknown")
        del self._pending[resolution_id]
        state = await self._dispatcher.reopen()
        return {"op_id": pending.op_id, "state": "failed", "gate": state.value}
