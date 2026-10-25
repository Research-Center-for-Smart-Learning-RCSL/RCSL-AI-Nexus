# Maintenance mode

Closing the platform for maintenance, releasing every runtime's memory, and
bringing the models back before reopening ([#61](https://github.com/Research-Center-for-Smart-Learning-RCSL/RCSL-AI-Nexus/issues/61)).
The design is on the issue; the code is `manage_maintenance.py`,
`maintenance_coordinator.py` and the node agent's `/v1/maintenance/*` routes.

**Status.** Entering is behind `MAINTENANCE_ENABLED`, which is off in
production. It stays off until the host acceptance at the end of this page has
passed.

**The console** (Dashboard → Maintenance) is where all of this is done:

- **Three milestones, shown apart:** access closed, runtimes released, models
  restored.
- **Each node's progress:** its phase, its snapshot, the requests that were
  interrupted, and any error.
- **Buttons:**
  - **Restore and reopen.** Disabled, with the reason, until a restore could
    put everything back.
  - **Retry.** Shown when a step has failed.
  - **Reopen without restoring.**

## What each button does

| Console button and call | Effect |
| --- | --- |
| **Close for maintenance**, `POST /admin/maintenance/enter` | Closes access at once and signs out every account that is not a platform administrator. It also records an entry, which the coordinator carries out on each node: interrupt, snapshot, reset and verify empty. |
| **Restore and reopen**, `POST /admin/maintenance/restore` | Loads each node's snapshot back, checks each model answers, and reopens the platform only once every node verifies. Allowed only after the entry has succeeded. |
| **Retry**, `POST /admin/maintenance/retry` | Runs the failed nodes of a failed entry or restore again, each from the phase it reached. The snapshot is kept. |
| **Reopen without restoring**, `POST /admin/maintenance/reopen` | Reopens without restoring. Never refused. Any entry or restore still running is abandoned. |

`GET /admin/maintenance` shows the latest operation. For each node it gives:

- the phase, the status, the attempts and the last error;
- the snapshot;
- the attempts the entry interrupted;
- whether the node's unknown operations were resolved.

## Prerequisites

- **Node agents.** `NODE_AGENT_ENABLED` must be on and every node needs an
  agent. Otherwise an entry is refused with `maintenance_unsupported`, before
  anything closes.
- **The control token in `admin-tailnet`.** The coordinator runs only where
  `node_agent_control_token` is mounted (`docker-compose.node-agent.yml`).
  Without it, an entry closes access, and its steps fail visibly instead of
  claiming that anything was released.
- **The runtime supervisor and the witness on the host.** See
  [runtime-supervisor.md](./runtime-supervisor.md).
  - The supervisor restarts the runtime.
  - The witness's two answers are what resolve interrupted attempts. Without
    them the runtime is still released, but the node reports
    `accounting: unresolved` and a restore is refused until those operations
    are resolved.

## When a step fails

The platform stays closed. Read the node's `error`, fix the cause, and press
retry.

| Error | Meaning and remedy |
| --- | --- |
| `senders still talking to the runtime` | The interrupt deadline passed with a sender still running. Retry. |
| `restart_failed` | The supervisor could not restart the runtime. Read its receipt. Retry starts a new restart. |
| `models are resident after the reset` | Something loaded a model under the hold. Find out what before you retry. |
| `model_not_on_node`, `revision_mismatch`, `context_length_mismatch` | The snapshot holds a model that is not registered on the node, or holds other weights or another context. The restore will not load something else instead. Fix the registration, or reopen and load the model by hand. |
| `repairs_exhausted` | Loads kept evicting each other, beyond the reconciler's repair rounds. Check the memory budget. |
| `models the snapshot did not hold are resident` | Something other than the restore loaded a model. |

**Restore is refused** in two cases. In both, reopening without a restore is
still available, and the models can be loaded by hand:

- the entry has no snapshot for a node, because its runtime could not be
  observed before the reset;
- the entry left unresolved unknown operations.

## Host acceptance (before enabling)

Do this in an operator-owned window with no traffic, on the Mac Studio.

1. Note the resident set and its memory:
   - `curl -s localhost:11434/api/ps`
   - `vm_stat` or Activity Monitor
2. With `MAINTENANCE_ENABLED=true` on `admin-tailnet` only, enter
   maintenance and start a long generation just before.
   - The generation is cut off.
   - The node's `interrupted` list names its attempt.
   - The entry succeeds.
3. Check that the runtime is empty and its memory released:
   - `ps` shows only the new daemon, and no `llama-server`;
   - `/api/ps` is empty;
   - the model memory is gone from the host.
4. Restore. Each model comes back on its node, with the context it had. The
   probes pass, and the platform reopens only after the last node verifies.
5. Confirm the end state:
   - an authenticated gateway request answers 200;
   - an API key works unchanged;
   - a non-admin session from before the entry is still signed out.
6. Record the timings: entry to empty, and restore to reopened. They set
   #61's deadlines.
