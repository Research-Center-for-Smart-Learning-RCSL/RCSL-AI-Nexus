"""The control-token client the maintenance coordinator talks to agents with (P4 on #61).

Separate from `NodeAgentRuntime`, which carries the data token every gateway
and admin process holds. This one carries the control token, which only the
tailnet admin mounts, and it reaches only the routes a maintenance entry needs:
interrupt, residency and the supervised reset. Each call is bounded by its own
timeout, set from what the agent itself waits for on that route, so a node that
hangs costs the coordinator one attempt rather than its lease.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.domain.ports.node_control_port import NodeControlError

INTERRUPT_TIMEOUT_S = 60.0
"""The agent's own interrupt deadline (10 s by default) and its audit write."""

RESIDENCY_TIMEOUT_S = 30.0
"""Two runtime reads of 10 s each, as `relay.residency` makes them."""

RESET_TIMEOUT_S = 420.0
"""The supervisor's 180 s, two witness answers of up to 30 s, and the 60 s the
agent waits for the new runtime to be attested, with room to spare. The call
is idempotent on its `reset_id`, so a timeout here is retried, not repeated."""


RESTORE_TIMEOUT_S = 900.0
"""A load of a large model from disk, or a probe on it. The call is
idempotent on its op id, so a timeout is asked again, not repeated."""


class NodeAgentControl:
    def __init__(
        self,
        agent_url: str,
        control_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = agent_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {control_token}"}
        self._transport = transport

    async def interrupt(self, epoch: int) -> dict[str, Any]:
        return await self._call(
            "POST", "/v1/maintenance/interrupt", {"epoch": epoch}, INTERRUPT_TIMEOUT_S
        )

    async def residency(self) -> list[dict[str, Any]] | None:
        try:
            observed = await self._call("GET", "/v1/residency", None, RESIDENCY_TIMEOUT_S)
        except NodeControlError:
            return None
        resident = observed.get("resident")
        return resident if isinstance(resident, list) else None

    async def reset(self, epoch: int, reset_id: str, *, operator: str) -> dict[str, Any]:
        return await self._call(
            "POST",
            "/v1/maintenance/reset",
            {"epoch": epoch, "reset_id": reset_id, "operator": operator},
            RESET_TIMEOUT_S,
        )

    async def restore(
        self,
        epoch: int,
        op_id: str,
        *,
        action: str,
        name: str,
        digest: str | None,
        context_length: int | None,
    ) -> dict[str, Any]:
        return await self._call(
            "POST",
            "/v1/maintenance/restore",
            {
                "epoch": epoch,
                "op_id": op_id,
                "action": action,
                "name": name,
                "digest": digest,
                "context_length": context_length,
            },
            RESTORE_TIMEOUT_S,
        )

    async def _call(
        self, method: str, path: str, body: dict[str, Any] | None, timeout_s: float
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._url,
                headers=self._headers,
                timeout=httpx.Timeout(timeout_s, connect=5.0),
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise NodeControlError(f"{path}: {type(exc).__name__}: {exc}") from exc
        try:
            document = response.json()
        except ValueError:
            document = None
        if not isinstance(document, dict):
            document = {}
        if response.status_code != 200:
            refused = document.get("refused")
            raise NodeControlError(
                f"{path} answered {response.status_code}: "
                f"{refused or document.get('detail') or response.text[:200]}",
                status=response.status_code,
                refused=refused if isinstance(refused, str) else None,
                body=document,
            )
        return document
