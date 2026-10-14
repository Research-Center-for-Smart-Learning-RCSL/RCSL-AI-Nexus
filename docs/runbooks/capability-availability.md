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
and its result is written before the next node is probed. Direct adapters still
observe only their configured local host. The request reader uses the database
wall clock after reading observations, so authentication's earlier transaction
start cannot make a newly committed heartbeat appear to come from the future.

This closes the observation fallback part of #49. It does not add desired
residency, automatic reload or runtime reset. After a real restart an operator
still restores the models in the documented largest-first order until the rest
of #49 ships. Unknown-operation blocks still require existing audited resolution;
an expired lease never clears them.

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

The remainder of #50 also needs #49's `desired_resident` and reconciler outcomes
before residency-mismatch metrics/alerts and reconcile counters can be added.
Those signals must not be synthesized from lifecycle `state`.
