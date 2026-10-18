# Capability availability and quiet-host alerts

`/readyz` checks dependencies. `GET /admin/capabilities/availability` rehearses
route selection against the registry, live policies, node health and residency
observations. It requires `routing:read`, is mounted only on the admin entrances,
and returns no model aliases or node identifiers. It never loads a model or
sends inference. A successful rehearsal is a snapshot, not a reservation or a
guarantee that a later request will pass capacity, authorization or agent admission.

The response lists every routable capability. `enabled: false` and
`reasons: ["no_policy"]` means no policy exists; that capability is not advertised
as available and is not alerted. Policies with no usable candidates are enabled
but unavailable. Reasons distinguish missing models/nodes, unhealthy nodes,
missing adapters, unresolved node operations, unknown/stale residency, absent
weights, policy state mismatch and insufficient/unknown free memory. Multiple
rejected candidates can contribute different reasons. An eligible fallback
still makes the capability available when the selector rejects the primary's
residency or policy requirements. If the selected model's adapter is missing or
its node is blocked, availability is false: the gateway currently does not retry
selection after those later gates, so the rehearsal must not invent a fallback.

## Routing evidence

Ollama must have a positive `loaded` observation no more than **90 seconds** old
on an online node. Missing observations and future timestamps refuse selection,
even when the registry's lifecycle state says loaded or the policy omits its
state requirement. The 90-second limit covers three default 30-second heartbeat
intervals. Deployments that disable the heartbeat or configure a longer interval
will stop routing Ollama once the evidence expires; keep that interval below
the freshness limit. A successful operator load becomes eligible after read-back.
MLX has no residency endpoint and retains the existing lifecycle-intent fallback.

With node agents enabled, each node/runtime is observed through its own agent,
and its result is written before the next node is probed. Each node/runtime
answer uses one database timestamp captured **before** its probe. That fixed
time is preserved across all model writes, so a slow probe or earlier database
write cannot make an old answer appear fresh. The clock transaction closes
before runtime I/O; clock failure never falls back to the later write time.
Direct adapters still observe only their configured local host. The request reader uses the database
wall clock after reading observations, so authentication's earlier transaction
start cannot make a newly committed heartbeat appear to come from the future.

This closes the observation fallback part of #49. Desired residency and the
reconciler below are implemented but **off by default**; until they are enabled
and accepted on the host, an operator still restores the models after a real
restart in the documented largest-first order. Unknown-operation blocks still
require existing audited resolution; an expired lease never clears them.

### Uncertain lifecycle operations

`load`, `unload` and `pull` now follow the same node-wide uncertainty rule as
inference, embeddings and summaries. A lost response, timeout or pull stream
without terminal success records `outcome_unknown`; the node refuses new
scheduler-changing work with 503 and `Retry-After: 60`. Agent takeover converts
every orphaned `running` operation to unknown, including lifecycle work. It
preserves the original sender generation, fences late completions, and cancels
queued `accepted` operations without sending them.

Read-only residency remains available, but neither a fresh resident model nor
an absent model proves an earlier operation has finished. The unresolved gauge
and capability alert therefore persist even on a quiet host, until the existing
audited resolution path verifies the ordered sender-gone, quiescence, baseline
and runtime-reset evidence. A reset before the baseline does not qualify. Use
the resolution procedure in [first deployment](./first-deploy.md). The automated
admin reset action remains an unfinished part of #49. The residency reconciler
never loads while any operation on the node is unknown.
If the Colima VM restarted while such an operation was open, the agent refuses
election until the previous kernel is released; see
[node-agent-kernel-change.md](./node-agent-kernel-change.md).

This supersedes PR4b's uncertainty exception recorded on 2026-10-09 and resolves
the decision requested by #49 section 6 in favor of #24 section 3's uniform
block. A completed response, explicit runtime refusal or proven unsent request
still allows reopening. This increases operator-visible blocking after a lost
lifecycle response; recovery requires evidence instead of a repeat load.
Historical rows already recorded as `failed` by the earlier implementation
are not reclassified, because their remote outcome cannot be reconstructed.

## Desired residency and the reconciler (#49)

Each model carries `desired_resident` and `desired_version`, separate from
lifecycle `state`. The migration sets `desired_resident = false` on every
row, deliberately not copied from `state = 'loaded'`: production models were
unloaded outside the registry, so a row can still say `loaded` for weights
nobody wants, and the reconciler would reload them unasked. Intent therefore
starts empty and the first operator Load after the upgrade records it. An
operator's Load sets it; Unload clears it; both bump
the version. `PUT /admin/models/{id}/residency-intent` (`model:write`, the
models table's **Stop restoring** button) changes it without touching the
runtime and answers `202` once the new version is committed. It is audited as
`model.residency_intent_changed` with outcome `accepted`. This is the
cancellation that works after a restart, when the model is observed
`downloaded` and Unload refuses. Withdrawing intent never unloads a resident
model; use Unload for that. `desired_version` versions intent only; the weights
pin remains `manifest_digest`.

Load and Unload commit the intent in their own transaction, once the request's
checks pass and before the runtime is called, never through the request
transaction (that held the row lock while a second connection wrote the same
row, and the request then waited on itself). So a refused Load or Unload (wrong
state, over budget) leaves the intent unchanged. A Load the runtime fails
leaves `state = error` and the intent set, and the reconciler retries it within
its backoff. An Unload the runtime fails leaves the model `loaded` and the
intent withdrawn.

`RESIDENCY_RECONCILER_ENABLED` (default `false`) starts a loop in the tailnet
admin, beside the heartbeat. It stays idle unless `NODE_AGENT_ENABLED` is on
and the heartbeat interval is positive. For each Ollama node it:

1. Acts only on a desired model with **two consecutive, distinct, fresh**
   `downloaded` observations. A failed, missing or stale probe restarts the
   count; MLX is never reloaded.
2. Skips the pass if the node is not online, has any `outcome_unknown`
   operation, has a model in `downloading`/`loading`/`unloading`, or another
   reconciler holds the node's advisory lock. Elapsed time is never a reason
   to proceed.
3. Restores largest `memory_gb` first, through `ManageModels.restore`: the same
   state transitions, memory budget, live free-memory check and audit as an
   operator's Load, and the agent's exclusive lifecycle path with the
   registered `num_ctx` and the deployment's `keep_alive` (production `-1`).
4. Re-reads intent and the block before every load. After each load it re-reads
   intent; weights whose intent was withdrawn during the load are unloaded
   (`model.unloaded` under the `residency-reconciler` subject). It then
   re-observes the whole node.
5. Re-queues any desired model still not resident, including evicted siblings,
   for at most two repair rounds. Then it backs off `30 s × 2^n` (cap 15 min)
   and needs two fresh observations again.
6. Gives up on the node after four consecutive failed passes that each loaded
   weights, while the node's intent is unchanged. A desired set that cannot
   co-reside would otherwise reload 30-40 GB every 15 minutes indefinitely.
   It logs `residency reconciler gave up on node ...` at error level once and
   then leaves the node alone. Failures that load nothing (a budget refusal,
   an outage) never count; they only back off. To retry, fix the cause (for
   example withdraw one model's intent) and change any intent on the node:
   Load, Unload or **Stop restoring** all bump a version. The give-up also
   clears when the whole desired set is observed resident, or when
   `admin-tailnet` restarts, since the count is held in memory.

Loads on one node are serialised by that advisory lock, whether the flag is
on or not: an operator's Load takes it for its own duration, and the
reconciler for its whole pass. Neither waits for the other. A Load while the
node is held answers `409` ("another load is in progress"); retry once the
pass or the other load finishes. Without the lock, two loads could each read
the occupying set before either recorded `loading`, and both pass the budget.

With the flag on, the memory budget also stops charging a model the runtime has
freshly reported as not resident. A mid-load model, a resident model, or one
with unknown or stale residency is still charged at its intent. With the flag
off, budgeting is unchanged.

**Before enabling:** resolve every model in `error`, `loading` or `unloading`.
Press Load on each model that should be kept resident (nothing is desired after
the upgrade), then check that the desired set is exactly what you want loaded
at boot (`SELECT alias, state, desired_resident FROM models`). Confirm no `outcome_unknown` operation
is open. A reconciler load in flight when the admin stops is treated like an
interrupted operator load: the agent still settles it. The stranded `loading`
row then holds the node's reconciler (it waits on any transient state) until
deploy-time provisioning moves it to `error`, which is retried on fresh
evidence.

**Suspension.** The loop takes a `suspended` hook that is checked before each
pass and before each load. Nothing supplies it yet; maintenance mode (#61) is
meant to. Until then, disable the flag and restart `admin-tailnet` to stop it.

**Not yet done.** The admin "reset runtime" action is not built. The witness
CLI resolution remains the only path, because the agent cannot restart the
host runtime and resolves one operation per witnessed restart. Host acceptance has not been
run: restart Ollama with no traffic in an operator-owned window, observe
gemma4, then qwen2.5:7b, then nomic-embed-text restored, and gate on an
authenticated gateway request, plus the five #23 gates.

## Metrics and delivery

The tailnet admin runs an independent, read-only loop every 30 seconds, with a
20-second deadline and a short repeatable-read PostgreSQL transaction. A stuck
runtime probe cannot stop this loop from aging out the last observation. The
agent need not be scraped. The loop publishes:

| Metric | Meaning |
| --- | --- |
| `nexus_capability_available{capability}` | 0 or 1 for each configured policy |
| `nexus_node_operation_unresolved{node}` | Number of durable `outcome_unknown` operations |
| `nexus_inference_silent_outage` | No completed usage in the last 24 hours, with at least one gateway refusal in that window |
| `nexus_availability_observed_at_seconds` | Database timestamp of the last successful snapshot |
| `nexus_model_residency_mismatch{alias}` | 1 when a model is desired resident but not shown resident, else 0; one series per registered model |

Residency mismatch uses the evidence routing uses. An Ollama model needs a
positive `loaded` observation no older than 90 seconds; unknown, stale or future
evidence counts as a mismatch. MLX cannot report residency, so its lifecycle
intent stands in, as it does for routing. A desired model whose weights are gone
is a mismatch even though the reconciler skips it: that is the case nobody else
reports. It is published whether or not the reconciler is enabled, so with the
flag off it shows exactly which wanted models a runtime restart has dropped.

The reconciler, which runs in the same process, also publishes
`nexus_residency_reconcile_total{outcome}`: one increment per node per pass, by
result (`idle`, `restored`, `failed`, `backing_off`, `blocked`, `busy`,
`unhealthy`, `suspended`, `gave_up`), plus `error` for a pass that raised before
judging any node. Every outcome is exported at zero when the loop starts. It is
absent while the flag is off.

Silent-outage status uses durable rows, so restarting gateway counters does not
erase a refusal or a success. Interrupted usage does not count as a success;
admin-surface refusals do not count as gateway traffic. It is a platform-wide
signal; the per-capability signal covers a partial outage. Failed reads preserve
the last snapshot timestamp. Deleted policies/nodes have their old labels removed
on the next successful sweep.

Prometheus loads [the rules](../../prometheus/availability.rules.yml) through a
read-only Compose mount. Rules select `job="admin-tailnet"`, the periodic owner:

- Capability unavailable for five minutes.
- Any unresolved operation, immediately.
- Silent inference outage, immediately.
- Observer older than 90 seconds or absent, for two minutes.
- A model desired resident but not shown resident, for ten minutes. A reload,
  which briefly empties the set, stays inside that window.
- The reconciler gave up on a node, immediately. After a give-up each later pass
  reports `gave_up` again, so the alert holds until intent changes or the set is
  resident. The mismatch alert would also fire, but this one says the automatic
  path has stopped and an operator must act.

The existing host health job reads firing `ALERTS` and feeds them into its Tier 1
failure signature. This reuses its configured recipients, change notifications,
recovery mail and dry-run mode. There is no second SMTP configuration or
Alertmanager. Delivery occurs on the next health-job run (normally within five
minutes), after Prometheus's pending timer. A failed alert query is itself a
Tier 1 failure. No mail was sent during development; the shell stage is tested
with synthetic firing, recovery and query-error responses.

## Verification and remaining rollout work

Run the deterministic alert scenarios with the deployed Prometheus version:

```sh
docker run --rm -v "$PWD/prometheus:/rules:ro" -w /rules \
  --entrypoint promtool prom/prometheus:v3.1.0 test rules availability.test.yml
```

CI runs these scenarios, including firing without incoming requests and clearing
after recovery. Backend tests use real PostgreSQL for lost/stale observations,
old unresolved operations and the rolling 24-hour usage/refusal window.

On 2026-10-13, an isolated Prometheus **v3.1.0** container scraped itself into a
named volume. After saving an `up=1` sample's timestamp, restarting the container,
and querying `up` at that exact historical time, it still returned `1`. This
verifies local container-restart persistence. The production Compose already
uses the named `prometheus-data` volume with 30-day retention.

**Production container and colima VM restart validation remain open.** In an
operator-owned window, save a successful query of a historical series and its
explicit `time`, restart Prometheus, query that same time, then repeat after a
colima VM restart. Record results and restore the production model set before
an authenticated gateway smoke test. The local container check does not claim
that host-specific acceptance.

Residency mismatch is read from `desired_resident`, never from lifecycle
`state`, which records the last operation rather than what is wanted.
