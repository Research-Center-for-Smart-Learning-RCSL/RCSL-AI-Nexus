# Node agent refuses election after a VM restart

[← First deploy runbook](./first-deploy.md)

This covers the node agent failing to start after the Colima VM restarted,
for example when the VM was killed during a long load (#47) and then brought
back, while work on the node was still `running` or `outcome_unknown`. It is
item 5 of #62.

## Symptom

`docker compose logs node-agent` shows the agent failing at start-up with:

```text
ElectionRefused: the kernel changed since the last owner and node <node id> has
<n> running or unknown operations; an operator must establish that the previous
kernel is gone
```

Every restart of the container fails the same way. Nothing reaches the runtime
through this node, and the resolve CLI (`app.node_agent.resolve`) cannot help,
because it talks to the agent that is refusing to start.

## Why the agent refuses

The host lock that proves an earlier agent is gone is a `flock`, and a `flock`
only excludes processes in the same kernel. Every owner records its kernel boot
id (`/proc/sys/kernel/random/boot_id`). A claimant in another kernel cannot
tell a restarted VM, where the previous agent is certainly gone, from a cloned
or restored lock volume running in a second VM, where it might still be alive
with an operation committed as `running` but not yet sent. While any operation
is open, election therefore refuses until an operator states which case it is
(design revision 4 on #24).

A VM restart does **not** prove that the runtime finished anything. Ollama runs
on the macOS host, outside the VM, so a load, pull or generation the old agent
started may still be running there. That is why the procedure below has two
separate steps: the operator releases the previous kernel, and then each open
operation is cleared with the runtime witness exactly as after any other
takeover. No operation is ever made terminal by the release itself, so billing
and usage settle through the one existing resolution path.

## Diagnosis

Use the same `COMPOSE_FILE` as the deployment (see
[first-deploy.md](./first-deploy.md)). Read the node's recorded owner, its open
operations and its recent audit trail:

```sh
docker compose exec -T postgres psql -U nexus -d nexus -c "
  SELECT node_id, generation, kernel_boot_id, started_at
    FROM node_agents WHERE node_id = '<node id>';"

docker compose exec -T postgres psql -U nexus -d nexus -c "
  SELECT op_id, kind, state, reason, origin_generation, submitted_at, running_at
    FROM node_operations
   WHERE node_id = '<node id>' AND state IN ('running', 'outcome_unknown')
   ORDER BY submitted_at;"

docker compose exec -T postgres psql -U nexus -d nexus -c "
  SELECT at, event, op_id, detail
    FROM node_operation_audit WHERE node_id = '<node id>'
   ORDER BY at DESC LIMIT 20;"
```

Read the kernel the VM runs now, from inside a container of the agent's own
service:

```sh
docker compose run --rm --no-deps node-agent cat /proc/sys/kernel/random/boot_id
```

If it equals `node_agents.kernel_boot_id`, this runbook does not apply: the
refusal has another cause, which the log names.

## Establish that the previous kernel is gone

This is the operator's statement that the release records. Make it only when
all of these are true, and write down what you checked:

- `colima list` shows one VM for this deployment, and it was restarted (its
  uptime from `colima ssh -- uptime` is shorter than the time since the
  previous agent's last activity in the audit trail).
- The `rcsl-node-agent-lock` volume has never been copied, restored from a
  backup or attached to another VM.
- No other machine runs this deployment's node agent for this node.

If any of these is uncertain, stop and escalate. Releasing a kernel that is
still alive lets two agents send to one runtime.

## Procedure

1. Stop the agent so the release can take the host lock:

   ```sh
   docker compose stop node-agent
   ```

2. Release the previous kernel. `--previous-kernel` is
   `node_agents.kernel_boot_id`, `--current-kernel` is the value read above.

   ```sh
   docker compose run --rm --no-deps node-agent \
     python -m app.node_agent.release_kernel \
       --node <node id> \
       --previous-kernel <recorded kernel boot id> \
       --current-kernel <current kernel boot id> \
       --operator <your name> \
       --reason "colima VM restarted after <cause>; one VM, lock volume never copied"
   ```

   It refuses, changing nothing, if the node is not this service's node, if
   either kernel id does not match, if an agent still holds the host lock or
   the node's election lock, if the node is bound to another lock domain, or if
   nothing is open. On success it prints the open operations and writes one
   `kernel_released` row to `node_operation_audit`.

3. Start the agent:

   ```sh
   docker compose up -d node-agent
   docker compose logs --tail 20 node-agent
   ```

   The log reports how many orphaned operations are now unknown, and the node
   starts blocked.

4. Clear each unknown operation with ordered reset evidence, one operation per
   run, as described at the top of `backend/app/node_agent/resolve.py`:

   ```sh
   docker compose run --rm --no-deps node-agent python -m app.node_agent.resolve start \
     --op <op id> --operator <your name> --evidence "kernel released; <what you relied on>"
   sudo launchctl kickstart -k system/online.rcsl.ollama
   docker compose run --rm --no-deps node-agent python -m app.node_agent.resolve complete \
     --resolution <resolution id>
   ```

   Each operation becomes `failed` with reason `resolved_by_reset`. Repeat for
   the next one; each needs its own runtime restart after its own baseline.

5. Load the resident models back in the documented order (gemma4, then qwen,
   then the embedder), as after any runtime restart.

## Verification

```sh
docker compose exec -T postgres psql -U nexus -d nexus -c "
  SELECT count(*) FROM node_operations
   WHERE node_id = '<node id>' AND state IN ('running', 'outcome_unknown');"

docker compose exec -T postgres psql -U nexus -d nexus -c "
  SELECT at, event, op_id FROM node_operation_audit
   WHERE node_id = '<node id>'
     AND event IN ('kernel_released', 'takeover', 'resolution_baseline', 'resolved_by_reset')
   ORDER BY at;"
```

The count is 0, `nexus_node_operation_unresolved{node}` returns to 0, and the
audit trail reads `kernel_released`, `takeover`, then a `resolution_baseline`
and `resolved_by_reset` pair for each operation.

Never update `node_agents` or `node_operations` by hand. The release and the
resolution are the only supported writers, and both leave the audit trail that
explains why the node was unblocked.
