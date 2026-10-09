"""Exactly-once usage for agent-backed attempts (design R6, S6, revision 6).

Three writers can reach one attempt's usage: the gateway when its stream ends,
the admin sweeper for an attempt nobody settled (the gateway died, or the
client left while the agent drained to `done`), and reconciliation of the
delivery flag. All of them go through this class:

- `settle` inserts the row once, keyed by the attempt, from the agent's
  terminal commit and the binding's billing snapshot. A row that exists is
  never rewritten, except by:
- reconciliation, which only turns `completed` from false to true, and only
  when the gateway committed that the client received everything.

Its own transactions: like the bindings, it must be visible to the other
writers when it commits, not when a request's session does.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.services.usage_settlement import BILLABLE_STATES, settle_usage

_FACTS = text(
    "SELECT a.op_id, a.client_delivery_complete, b.billing, b.tenant_id, "
    "o.state, o.terminal, o.observed, o.provenance "
    "FROM request_attempts a "
    "JOIN request_bindings b ON b.tenant_id = a.tenant_id AND b.request_id = a.request_id "
    "JOIN node_operations o ON o.node_id = a.node_id AND o.op_id = a.op_id "
    "WHERE a.op_id = :op_id"
)

_INSERT = text(
    "INSERT INTO usage_records (id, attempt_id, actor_id, api_key_id, tenant_id, capability, "
    "requested_capability, model_alias, tokens, prompt_tokens, latency_ms, completed, at, "
    "compaction_tier, tokens_before_compaction, tokens_after_compaction, totals_source, "
    "prompt_tokens_basis, runtime_completed) "
    "VALUES (:id, :attempt_id, :actor_id, :api_key_id, :tenant_id, :capability, "
    ":requested_capability, :model_alias, :tokens, :prompt_tokens, :latency_ms, :completed, "
    ":at, :compaction_tier, :tokens_before, :tokens_after, :totals_source, "
    ":prompt_tokens_basis, :runtime_completed) "
    "ON CONFLICT (attempt_id) DO NOTHING"
)

# Monotonic and idempotent: false to true, nothing else, and only on the
# attempt's own delivery evidence (revision 6; `request_attempts.op_id` is
# unique, so no other attempt can be reached through it).
_RECONCILE = text(
    "UPDATE usage_records SET completed = true "
    "WHERE attempt_id = :op_id AND completed = false "
    "AND EXISTS (SELECT 1 FROM request_attempts "
    "WHERE op_id = :op_id AND client_delivery_complete IS TRUE)"
)


class PostgresUsageSettlement:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def mark_delivery(self, op_id: str, complete: bool) -> None:
        """What the gateway saw of delivery, recorded once.

        Only the first observation is kept: a delivery is not delivered and
        then undelivered.
        """
        async with self._sessions() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE request_attempts SET client_delivery_complete = :complete "
                    "WHERE op_id = :op_id AND client_delivery_complete IS NULL"
                ),
                {"op_id": op_id, "complete": complete},
            )

    async def settle(self, op_id: str) -> bool:
        """Write the attempt's usage row if it is billable and has none, then
        reconcile delivery. False while the attempt is not terminal yet."""
        async with self._sessions() as session, session.begin():
            facts = (await session.execute(_FACTS, {"op_id": op_id})).mappings().first()
            if facts is None or facts["state"] not in BILLABLE_STATES:
                return False
            billing = _json(facts["billing"])
            compaction = billing.get("compaction") or {}
            usage = settle_usage(
                state=facts["state"],
                terminal=_json(facts["terminal"]),
                observed=_json(facts["observed"]),
                provenance=_json(facts["provenance"]),
                started_at=datetime.fromisoformat(billing["started_at"]),
                delivered=facts["client_delivery_complete"],
            )
            await session.execute(
                _INSERT,
                {
                    "id": str(uuid.uuid4()),
                    "attempt_id": op_id,
                    "actor_id": billing["actor_id"],
                    "api_key_id": billing.get("api_key_id"),
                    "tenant_id": facts["tenant_id"],
                    "capability": billing["capability"],
                    "requested_capability": billing.get("requested_capability"),
                    "model_alias": billing["model_alias"],
                    "tokens": usage.tokens,
                    "prompt_tokens": usage.prompt_tokens,
                    "latency_ms": usage.latency_ms,
                    "completed": usage.completed,
                    "at": usage.at,
                    "compaction_tier": compaction.get("tier"),
                    "tokens_before": compaction.get("tokens_before"),
                    "tokens_after": compaction.get("tokens_after"),
                    "totals_source": usage.totals_source,
                    "prompt_tokens_basis": usage.prompt_tokens_basis,
                    "runtime_completed": usage.runtime_completed,
                },
            )
            await session.execute(_RECONCILE, {"op_id": op_id})
        return True

    async def sweep(self, limit: int = 100) -> int:
        """Settle what nobody settled, and reconcile what was settled early.

        Run by the admin entrance, never the gateway: it covers the gateway
        dying between the agent's terminal commit and its own usage write.
        Returns how many attempts it settled.
        """
        async with self._sessions() as session:
            pending = (
                (
                    await session.execute(
                        text(
                            "SELECT a.op_id FROM request_attempts a "
                            "JOIN node_operations o ON o.node_id = a.node_id AND o.op_id = a.op_id "
                            "WHERE o.state IN ('completed', 'failed') "
                            "AND NOT EXISTS (SELECT 1 FROM usage_records u "
                            "WHERE u.attempt_id = a.op_id) "
                            "ORDER BY a.created_at LIMIT :limit"
                        ),
                        {"limit": limit},
                    )
                )
                .scalars()
                .all()
            )
            late = (
                (
                    await session.execute(
                        text(
                            "SELECT u.attempt_id FROM usage_records u "
                            "JOIN request_attempts a ON a.op_id = u.attempt_id "
                            "WHERE u.completed = false AND a.client_delivery_complete IS TRUE "
                            "LIMIT :limit"
                        ),
                        {"limit": limit},
                    )
                )
                .scalars()
                .all()
            )
        settled = 0
        for op_id in pending:
            settled += await self.settle(op_id)
        for op_id in late:
            async with self._sessions() as session, session.begin():
                await session.execute(_RECONCILE, {"op_id": op_id})
        return settled


def _json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}
