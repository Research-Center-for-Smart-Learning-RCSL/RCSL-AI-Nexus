# Runtime supervisor

The root LaunchDaemon that stops, starts and restarts the native Ollama for the
node agent. It is P3 of [#61](https://github.com/Research-Center-for-Smart-Learning-RCSL/RCSL-AI-Nexus/issues/61),
chosen by the maintainer on 2026-10-24 over a manual restart. The reasoning is
at the top of `scripts/host/runtime_supervisor.py`; this page covers installing
it, checking it and taking it out.

## What it may do

- **Actions.** A request names one of three: `stop`, `start` or `restart`.
- **Targets.** These come from its launchd arguments, never from a request:
  - the job `online.rcsl.ollama`;
  - its plist in `/Library/LaunchDaemons`;
  - the `_rcslollama` account;
  - the process name `ollama`.
- **Stop.**
  1. Unloads the job with `launchctl bootout`, so `KeepAlive` cannot respawn it.
  2. Waits for the daemon and every model runner to exit.
  3. Sends SIGTERM, then SIGKILL, to anything still running. Each signal is sent
     only after re-reading that process's PID and start time and finding them
     unchanged.
  4. Succeeds only if a fresh scan finds no runtime process.
- **Start.** Bootstraps the plist.
- **Restart.** A stop, then a start whose daemon must be a new process.
- **Receipts.** Every request leaves a receipt, and no request runs twice.

The agent writes `data/runtime-supervisor/requests` and reads
`data/runtime-supervisor/receipts`, which is mounted into it read-only. The
supervisor refuses to start unless `receipts` belongs to root and only root can
write it.

## Install

Run this once on the host, from the checkout, after the PR is merged and
deployed:

```sh
openssl rand -hex 32 | tr -d '\n' > secrets/node_agent_control_token && chmod 600 secrets/node_agent_control_token
mkdir -p data/runtime-supervisor/requests
sudo install -d -o root -g wheel -m 755 data/runtime-supervisor/receipts
sudo launchd/install-daemons.sh --reload runtime-supervisor
```

- **Control token.** `secrets/node_agent_control_token` is new.
  - It must be different from `secrets/node_agent_token`. The agent refuses to
    start if the two are the same.
  - Only the agent mounts it. The gateway never does.
  - The `drain`, `resume` and resolution routes moved to this token, and so did
    the resolve CLI.
- **Recreate the agent.** It reads secrets and mounts only when it is created:
  ```sh
  docker compose up -d --no-deps node-agent
  ```

## Check

```sh
launchctl print system/online.rcsl.runtime-supervisor | grep -E 'state|pid'
tail -5 /opt/homebrew/var/log/nexus-runtime-supervisor.log
docker compose run --rm --no-deps node-agent python -m app.node_agent.resolve status
```

- **Job.** `state = running` with a PID, and the log has no "must be owned by
  root" line.
- **Agent status.** `supervisor_available` is `true`, which means both
  directories are mounted. It does not say the job is running; the log does.
  `gate` is `serving`.

## Host acceptance

Do this in a maintenance window, with no traffic: it restarts Ollama, and the
residency reconciler then reloads the resident set.

```sh
R="docker compose run --rm --no-deps node-agent python -m app.node_agent.resolve"
$R drain
$R runtime restart --operator <name> --reason "P3 acceptance"
$R resume
```

1. **The receipt says the restart worked.**
   - `result` is `ok`.
   - `before` lists the old daemon and its runners.
   - `after` lists only the new daemon.
   - The steps run `bootout`, `unloaded`, `bootstrap`, `started`. A `SIGTERM` or
     `SIGKILL` step is allowed when a runner outlived the bootout.
2. **Nothing of the old instance is left.** `ps -axo pid,user,lstart,comm | grep
   _rcslollama` shows only the new daemon's PID until models load.
3. **Service comes back.**
   - The reconciler restores the resident set, as in the 2026-10-22 acceptance
     in [capability-availability.md](./capability-availability.md).
   - An authenticated chat request then answers 200.
4. **Measure the timings.**
   - Note how long the stop took from `bootout` to `stopped`, and the start
     from `bootstrap` to `started`.
   - #61 needs these measured before its deadlines are set.

A supervised reset of an `outcome_unknown` block works the same way. It is one
command instead of the `start`, manual restart and `complete` sequence:

```sh
$R reset --op <op_id> --operator <name> --evidence "<what you relied on>"
```

The resolution's evidence records the supervisor's receipt beside the witness's
two answers. If the restart fails, the block stays and the node stays drained.

## Remove

```sh
sudo launchctl bootout system/online.rcsl.runtime-supervisor
sudo rm /Library/LaunchDaemons/online.rcsl.runtime-supervisor.plist
```

A runtime-control request then waits out `NODE_AGENT_SUPERVISOR_TIMEOUT`
(180 s), is withdrawn unexecuted, and is refused with `supervisor_unanswered`.
Everything else carries on, because nothing the agent serves depends on the
supervisor.
