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
from app.node_agent.supervisor import Supervisor, SupervisorRefused

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

    async def complete(
        self, resolution_id: str, *, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
            **(extra or {}),
        }
        if not await self._store.resolve_unknown(pending.op_id, evidence):
            del self._pending[resolution_id]
            raise ResolutionRefused(f"{pending.op_id} is no longer unknown")
        del self._pending[resolution_id]
        state = await self._dispatcher.reopen()
        return {"op_id": pending.op_id, "state": "failed", "gate": state.value}

    async def reset(
        self,
        op_id: str,
        *,
        evidence: str,
        operator: str,
        supervisor: Supervisor,
        settle_s: float = 60.0,
        retry_s: float = 2.0,
    ) -> dict[str, Any]:
        """Steps 1 to 5 in one call, with the supervisor as step 4 (#49 §5, #61).

        The same ordered evidence as the CLI path: the baseline is taken after
        the sender is gone and this agent has drained, then the supervisor
        restarts the runtime, then a second challenge must show another
        instance. The supervisor's receipt, which proves the old daemon and
        its runners exited, is recorded beside the witness's two answers; it
        does not replace them. A failed restart leaves the node drained and
        the block in place: nothing reopens on a partial reset.
        """
        started = await self.start(op_id, evidence=evidence, operator=operator)
        resolution_id = started["resolution_id"]
        try:
            receipt = await supervisor.run("restart", f"reset for {op_id} by {operator}")
        except SupervisorRefused as exc:
            self._pending.pop(resolution_id, None)
            raise ResolutionRefused(f"the runtime supervisor did not restart: {exc}") from exc
        await self._store.audit(
            "resolution_restart", op_id, {"resolution_id": resolution_id, "receipt": receipt}
        )
        if receipt.get("result") != "ok":
            self._pending.pop(resolution_id, None)
            raise ResolutionRefused(
                f"the runtime supervisor could not restart the runtime: {receipt.get('error')}"
            )
        # The new daemon may not be listening yet, and the witness answers on
        # its own cycle: retried while the resolution is still pending, which
        # a witness restart (a new incarnation) ends.
        deadline = time.monotonic() + settle_s
        while True:
            try:
                return await self.complete(resolution_id, extra={"supervisor_receipt": receipt})
            except ResolutionRefused:
                if resolution_id not in self._pending or time.monotonic() >= deadline:
                    self._pending.pop(resolution_id, None)
                    raise
                await asyncio.sleep(retry_s)

    async def maintenance_reset(
        self,
        *,
        epoch: int,
        reset_id: str,
        operator: str,
        supervisor: Supervisor,
        settle_s: float = 60.0,
        retry_s: float = 2.0,
    ) -> dict[str, Any]:
        """Restart the runtime empty for a maintenance entry, and clear what
        the restart proves gone (P4 on #61).

        The caller has frozen the gate for `epoch` and found no sender left,
        which is steps 1 and 2 of the ordered evidence for every operation on
        the node at once. Then the same baseline, supervised restart and
        second answer as `reset`, and every `outcome_unknown` whose sender is
        gone is resolved on that evidence. The gate is not reopened: it stays
        frozen until the platform's hold lifts.

        Named by the caller and resumable. The baseline, the receipt and the
        outcome are written to the audit under `reset_id` as they happen, and
        the supervisor request carries the same id, so asking again after a
        timeout or an agent restart continues from what was recorded and
        never restarts the runtime twice. A restart the witness could not
        attest still releases the runtime; it only leaves the unknowns, and
        the report says `accounting: unresolved` and why.
        """
        done = await self._store.audited("maintenance_reset_done", reset_id)
        if done is not None:
            return done

        recorded = await self._store.audited("maintenance_reset_baseline", reset_id)
        baseline: Attestation | None = None
        unwitnessed: str | None = None
        # The operations this reset can speak for: unknown, or still settling,
        # when the baseline was taken with no sender left. Anything sent after
        # it reached a runtime this restart may not have ended (review of #80).
        cohort: list[str] = []
        if recorded is not None:
            baseline = Attestation(**recorded["baseline"])
            cohort = [str(op) for op in recorded.get("cohort") or []]
        elif supervisor.receipt(reset_id) is not None:
            unwitnessed = "the runtime restarted before a witness baseline was recorded"
        else:
            cohort = sorted(
                set(await self._store.unknown_ops()) | set(self._dispatcher.admitted_ops)
            )
            try:
                baseline = await self._witness.attest()
            except ResolutionRefused as exc:
                unwitnessed = str(exc)
            else:
                await self._store.audit(
                    "maintenance_reset_baseline",
                    None,
                    {
                        "reset_id": reset_id,
                        "epoch": epoch,
                        "operator": operator,
                        "baseline": asdict(baseline),
                        "cohort": cohort,
                    },
                )

        if supervisor.receipt(reset_id) is None:
            # Read again just before the restart: the platform may have been
            # reopened while the baseline was taken, and a restart then would
            # cut off work the platform is serving.
            closed, current = await self._store.maintenance_hold()
            if not closed or current != epoch:
                raise ResolutionRefused(f"the hold for epoch {epoch} is no longer closed")
        receipt = await supervisor.run(
            "restart", f"{operator}: maintenance epoch {epoch}", request_id=reset_id
        )
        await self._store.audit(
            "maintenance_reset_receipt", None, {"reset_id": reset_id, "receipt": receipt}
        )
        if receipt.get("result") != "ok":
            raise ResetFailed(receipt)

        after: Attestation | None = None
        if baseline is not None:
            after, unwitnessed = await self._after(baseline, settle_s=settle_s, retry_s=retry_s)

        resolved: list[str] = []
        if after is not None and baseline is not None:
            closed, current = await self._store.maintenance_hold()
            if not closed or current != epoch or self._dispatcher.frozen_epoch != epoch:
                # Work admitted after a reopen may be unknown now too, and
                # the cohort alone cannot tell this restart covered the
                # runtime it reached: resolve nothing.
                after, unwitnessed = None, "the hold was lifted during the reset"
        if after is not None and baseline is not None:
            unknown_now = set(await self._store.unknown_ops())
            for op_id in [op for op in cohort if op in unknown_now]:
                operation = await self._store.observe(op_id)
                if operation is None or self._dispatcher.holds(op_id):
                    continue
                evidence = {
                    "reset_id": reset_id,
                    "maintenance_epoch": epoch,
                    "operator": operator,
                    "sender": (
                        "earlier agent; this agent holds the host lock"
                        if operation.origin_boot_id != self._store.ownership.boot_id
                        else "this agent; its task for the operation has ended"
                    ),
                    "baseline": asdict(baseline),
                    "after": asdict(after),
                    "supervisor_receipt": receipt,
                    "resolver_generation": self._store.ownership.generation,
                    "resolver_boot_id": self._store.ownership.boot_id,
                }
                if await self._store.resolve_unknown(op_id, evidence):
                    resolved.append(op_id)

        remaining = await self._store.unknown_ops()
        # Admitted work still settling is an unknown not yet committed, which
        # the database cannot list; the node is not reconciled until it lands.
        settling = self._dispatcher.admitted
        report: dict[str, Any] = {
            "reset_id": reset_id,
            "epoch": epoch,
            "operator": operator,
            "supervisor_receipt": receipt,
            "baseline": asdict(baseline) if baseline is not None else None,
            "after": asdict(after) if after is not None else None,
            "resolved": resolved,
            "remaining_unknown": remaining,
            "settling": settling,
            "accounting": "resolved" if not remaining and not settling else "unresolved",
            "accounting_error": unwitnessed if remaining or settling else None,
        }
        await self._store.audit("maintenance_reset_done", None, report)
        return report

    async def _after(
        self, baseline: Attestation, *, settle_s: float, retry_s: float
    ) -> tuple[Attestation | None, str | None]:
        """The second answer, retried while the new daemon starts listening."""
        deadline = time.monotonic() + settle_s
        while True:
            try:
                after = await self._witness.attest()
            except ResolutionRefused as exc:
                reason = str(exc)
            else:
                if after.incarnation != baseline.incarnation:
                    return None, "the witness restarted since the baseline"
                if after.seq > baseline.seq and after.instance != baseline.instance:
                    return after, None
                reason = (
                    "the witness does not see a new runtime instance "
                    f"(pid {after.pid}, started {after.start_time})"
                )
            if time.monotonic() >= deadline:
                return None, reason
            await asyncio.sleep(retry_s)


class ResetFailed(Exception):  # noqa: N818 - the supervisor's answer, reported as such
    def __init__(self, receipt: dict[str, Any]) -> None:
        super().__init__(f"the runtime supervisor could not restart: {receipt.get('error')}")
        self.receipt = receipt
