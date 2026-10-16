"""The audited CLI that releases a node from its previous kernel (#62, item 5).

    docker compose stop node-agent
    docker compose run --rm --no-deps node-agent python -m app.node_agent.release_kernel \
        --node <node id> --previous-kernel <recorded boot id> \
        --current-kernel <this VM's boot id> --operator <name> --reason "<what you checked>"
    docker compose up -d node-agent
    #   ... then clear each unknown operation with `app.node_agent.resolve` ...

Election refuses a claimant whose kernel boot id differs from the last
owner's while any operation on the node is `running` or `outcome_unknown`
(design revision 4). The host lock is a `flock`, which proves an earlier
sender is gone only within one kernel: from a new kernel, nothing can observe
whether the previous one, and an agent in it that committed `running` but has
not yet sent, still exists. The usual case is the same Colima VM restarted,
where it provably does not; the other is a cloned or restored volume, where it
might. Only the operator can tell them apart, so this records the operator's
statement that the previous kernel is gone, and nothing more.

What it deliberately does **not** do is resolve any operation. The runtime is
on the macOS host, outside the VM, so a VM restart says nothing about whether
a load, pull or generation is still running there; that is what the ordered
reset evidence in `resolution.py` proves, and it stays the only way an
unknown operation becomes terminal. After this command the agent is elected
normally, its takeover turns `running` into `outcome_unknown` exactly as after
any takeover, the node starts blocked, and `app.node_agent.resolve` clears each
operation with the witness, so billing and usage settle through the one
existing path.

It refuses, changing nothing, unless all of these hold:

- `--node` is the node this service is configured for;
- `--current-kernel` is the kernel this process runs in;
- `--previous-kernel` is the kernel recorded for the node's last owner, and
  differs from the current one;
- this process obtains the domain's host lock, so no agent of this domain
  runs in this kernel, and the node's election lock, so no agent holds the
  node anywhere;
- the node is bound to this lock domain and has open operations.

The release is one transaction: it rebinds the node's recorded kernel to the
current one, compare-and-set on the stated previous kernel, and writes a
`kernel_released` row to `node_operation_audit` naming the operator, the
reason, both kernels and every open operation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import asyncpg

from app.node_agent.lock_domain import HostLock, LockDomainError, LockHeld, kernel_boot_id
from app.node_agent.settings import AgentSettings
from app.node_agent.store import DISPATCH_NAMESPACE, ELECTION_NAMESPACE


class ReleaseRefused(Exception):  # noqa: N818 - a refusal, reported as such
    """The previous kernel may not be released; the reason says why."""


async def release_previous_kernel(
    conn: asyncpg.Connection,
    node_id: str,
    host_lock: HostLock,
    *,
    previous_kernel_boot_id: str,
    current_kernel_boot_id: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    """Rebind the node to the current kernel, or raise `ReleaseRefused`.

    `conn` must be a dedicated connection; the election lock is taken on it
    for the transaction and released before returning. `host_lock` is held by
    the caller and goes with its process, like the agent's.
    """
    if not operator.strip() or not reason.strip():
        raise ReleaseRefused("an operator and a reason are required")
    if not previous_kernel_boot_id or not current_kernel_boot_id:
        raise ReleaseRefused("both kernel boot ids are required")
    if previous_kernel_boot_id == current_kernel_boot_id:
        raise ReleaseRefused("the stated previous and current kernels are the same")
    if not host_lock.still_held():
        raise ReleaseRefused("the host lock is no longer this domain's lock file")
    if not await conn.fetchval(
        "SELECT pg_try_advisory_lock($1, hashtext($2))", ELECTION_NAMESPACE, node_id
    ):
        raise ReleaseRefused(f"an agent holds node {node_id}; stop it first")
    domain_id = host_lock.domain.domain_id
    try:
        async with conn.transaction():
            # The same lock order as election: dispatch, `node_agents`, `nodes`.
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1, hashtext($2))", DISPATCH_NAMESPACE, node_id
            )
            agent = await conn.fetchrow(
                "SELECT generation, boot_id, kernel_boot_id FROM node_agents "
                "WHERE node_id = $1 FOR UPDATE",
                node_id,
            )
            if agent is None:
                raise ReleaseRefused(f"node {node_id} has never had an agent")
            bound = await conn.fetchval(
                "SELECT lock_domain_id FROM nodes WHERE id = $1 FOR NO KEY UPDATE", node_id
            )
            if bound != domain_id:
                raise ReleaseRefused(
                    f"node {node_id} is bound to lock domain {bound}, not {domain_id}"
                )
            if agent["kernel_boot_id"] != previous_kernel_boot_id:
                raise ReleaseRefused(
                    f"node {node_id}'s last owner ran in kernel {agent['kernel_boot_id']}, "
                    f"not {previous_kernel_boot_id}"
                )
            rows = await conn.fetch(
                "SELECT op_id, kind, state, origin_generation FROM node_operations "
                "WHERE node_id = $1 AND state IN ('running', 'outcome_unknown') "
                "ORDER BY submitted_at, op_id",
                node_id,
            )
            if not rows:
                raise ReleaseRefused(
                    f"node {node_id} has no running or unknown operations; "
                    "the agent is elected without a release"
                )
            operations = [dict(row) for row in rows]
            await conn.execute(
                "UPDATE node_agents SET kernel_boot_id = $2 WHERE node_id = $1",
                node_id,
                current_kernel_boot_id,
            )
            detail = {
                "operator": operator,
                "reason": reason,
                "previous_kernel_boot_id": previous_kernel_boot_id,
                "current_kernel_boot_id": current_kernel_boot_id,
                "domain_id": domain_id,
                "generation": agent["generation"],
                "boot_id": agent["boot_id"],
                "operations": operations,
            }
            await conn.execute(
                "INSERT INTO node_operation_audit (node_id, op_id, event, detail) "
                "VALUES ($1, NULL, 'kernel_released', $2::jsonb)",
                node_id,
                json.dumps(detail),
            )
    finally:
        await conn.execute(
            "SELECT pg_advisory_unlock($1, hashtext($2))", ELECTION_NAMESPACE, node_id
        )
    return {
        **detail,
        "next": "start the agent, then resolve each operation with app.node_agent.resolve",
    }


def check_invocation(
    args: argparse.Namespace, *, configured_node: str, running_kernel: str | None
) -> None:
    """The checks that need neither the lock nor the database."""
    if args.node != configured_node:
        raise ReleaseRefused(f"this service is configured for node {configured_node}")
    if running_kernel is None:
        raise ReleaseRefused("this process cannot read its kernel boot id")
    if args.current_kernel != running_kernel:
        raise ReleaseRefused(f"this process runs in kernel {running_kernel}")


async def _run(args: argparse.Namespace, settings: AgentSettings) -> dict[str, Any]:
    check_invocation(args, configured_node=settings.node_id, running_kernel=kernel_boot_id())
    # Never `initialise`: a domain that does not exist yet has no previous owner.
    host_lock = HostLock.acquire(settings.lock_dir)
    conn = await asyncpg.connect(settings.dsn)
    try:
        return await release_previous_kernel(
            conn,
            args.node,
            host_lock,
            previous_kernel_boot_id=args.previous_kernel,
            current_kernel_boot_id=args.current_kernel,
            operator=args.operator,
            reason=args.reason,
        )
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--node", required=True)
    parser.add_argument("--previous-kernel", required=True)
    parser.add_argument("--current-kernel", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args, AgentSettings()))  # type: ignore[call-arg]
    except (ReleaseRefused, LockHeld, LockDomainError) as exc:
        print(json.dumps({"refused": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
