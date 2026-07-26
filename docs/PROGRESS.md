# Progress Log

What has actually been built, in the order it happened, and what was learned
doing it. Newest first.

This is the narrative record. Two other places describe state and neither
replaces this one:

- [`ROADMAP.md`](./ROADMAP.md) is the plan, item by item.
- [`architecture/security.md`](./architecture/security.md) section 13.0 is a
  checked control-by-control inventory of what exists.

If those two disagree with this file, they are wrong: update them here first
and propagate. The reason for saying so is that they have already drifted once.

---

## 2026-07-26

### FileVault deferred, and the headless prerequisites the runbook was missing

The Mac Studio was powered on for the first time, which turned the first-deploy
runbook from a document into something being executed and immediately surfaced a
decision the documents had stated but never sequenced.

`security.md` §9.3 says to keep FileVault enabled and argues it well: physical
theft in a shared facility is worth more than reboot convenience. What it
assumed was the UPS that makes the reboot cost rare, and the UPS is Phase 3 and
does not exist yet. On a headless machine with no UPS, an encrypted disk means
every power cut takes the platform down until someone walks to it, because the
pre-boot unlock happens before there is any network, Tailscale, or SSH. So
FileVault is off for the first deployment, and the UPS is the trigger to turn it
on. Recorded as an accepted risk in §15.6 rather than left as a silent
divergence from §9.3, which still holds as a position.

The decision has a consequence chain worth writing down, because two of its
three links are invisible until something fails to come back after a reboot:
FileVault off is what makes automatic login available, automatic login is what
produces a logged-in desktop session, and that session is what Docker Desktop
needs in order to autostart. Without it the containers' `restart: unless-stopped`
never gets the chance to matter. Enabling FileVault later breaks the first link
and restores the second by a different route, since the pre-boot unlock doubles
as the login.

Working the question through turned up three prerequisites the runbook did not
have, all of which must happen before the monitor is removed rather than after:
remote login, restart-after-power-failure, and startup security. The last one
changes weight rather than appearing from nowhere. §11 already required Full
Security, but with FileVault off it becomes the main control against booting
from external media instead of a second layer behind encryption.

---

## 2026-07-26

### Inference served end to end, and a model that could never leave its initial state

`POST /v1/chat/completions` now works on the target hardware, streaming and not,
from socket through key verification, quota, the trusted-proxy check, the country
filter, the routing policy, the GPU, SSE framing, and back out to a usage record.
That is Phase 1's stated goal observed rather than argued.

Non-streaming returned in 0.51s with `finish_reason=stop`. Streaming produced
twelve frames in the OpenAI envelope — a role frame, content deltas, a terminal
frame carrying `finish_reason`, then `[DONE]` — and reassembled correctly.
`usage_records` holds one row per successful request, stamped with the default
tenant; the two requests that were refused earlier in the path recorded nothing,
which is right, because neither reached the use case. The gateway's `/metrics`
reports `nexus_inference_requests_total 2` and `nexus_inference_tokens_total 33`,
matching the two completions exactly. The admin chat panel had produced two
further usage rows and no gateway metrics, which is also right: it is served by
the admin entrance, not the gateway.

Two things about the request shape are worth writing down, because both looked
like faults for a minute. The OpenAI `model` field carries the **capability**,
not a model alias — `RouteChatRequest` resolves a policy by capability and the
policy chooses the model, so `"model": "qwen7b"` is refused with
`no_available_model` while `"model": "chat"` succeeds. And in production the
gateway refuses anything that did not arrive through the proxy, so testing before
nginx exists means presenting `X-Nexus-Proxy` and an `X-Forwarded-For`. Both
refusals were the design working; neither is documented anywhere a caller would
look, which the API reference should fix when it exists.

**Before any of that, a registered model could not be downloaded at all.**
`model-table.tsx` offered `Unload` when the state was `loaded` and `Load` in every
other case — including `not_downloaded`, where the use case's precondition
guarantees a 409. A freshly registered model was therefore a dead end: the only
button available was the one that could not work. The backend endpoint, the
`startDownload` client, the `useStartDownload` hook, the `useDownloadJob` poller
and the `DownloadProgress` component all existed; the hook and the component were
never referenced from anywhere. The whole download UI was built and never wired
in, which is why `ROADMAP.md` could carry `features/models: download progress via
useDownloadJob` as done, and why this file could claim the models table polls that
endpoint. It does not; nothing did.

The actions now mirror the use cases' own preconditions, so a button that is
present is a button that can succeed: `Download` unless the model is loaded,
`Load` only from `downloaded`, `Unload` only from `loaded`. The table also owns
the job now, because `useDownloadJob` stops polling at a terminal state without
telling anyone, so the row would otherwise sit at `downloading` until a reload.

A measurement worth keeping: the loaded model is 5.7 GB resident against 4.7 GB of
weights, where the same model measured 6.6 GB this morning under a hand-started
`ollama serve`. The difference is `OLLAMA_KV_CACHE_TYPE=q8_0`, which the committed
plist carries and an ad-hoc run does not — so the KV cache the memory budget's
headroom has to absorb is about 1.0 GB here, not 1.9 GB.

### The stack is up on the Mac Studio, and the frontend could not reach its backend

First full `docker compose up` on the target hardware. `migrate` exited 0 having
logged `database roles provisioned: nexus_gateway(gateway), nexus_admin(admin)`,
all ten containers came up, and the gateway's `/readyz` returned all three checks
true — including `runtime`, which means the container reached the native Ollama
through `host.docker.internal` for real rather than in a test.

**The account split is now enforced by the deployed database, on this machine.**
`pg_stat_activity` shows the gateway connected as `nexus_gateway` and the two
admin entrances as `nexus_admin`. As `nexus_gateway`: `SELECT` on `api_keys` and
`routing_policies` succeeds, `INSERT` into `usage_records` succeeds, and `INSERT`
into `api_keys`, `users` and `audit_log` are each refused with `permission
denied`. That is the §6 property proven where it finally matters. The published
ports match §3.2 exactly: gateway and admin-public on the tailnet address only,
admin-tailnet on loopback only, nothing on `0.0.0.0`.

**Then the management UI turned out to be unreachable, for a reason that
`docker inspect` actively hides.** Every `/admin/*` call from either frontend
failed, the log reading `Failed to proxy http://localhost:8001/admin/me
ECONNREFUSED`, while the container's environment plainly carried
`ADMIN_API_URL=http://admin-tailnet:8001`. The rewrite lived in
`next.config.js`, and `output: 'standalone'` serialises the resolved config into
`.next/required-server-files.json` at build time — so `process.env.ADMIN_API_URL`
was read during `pnpm build`, where the Dockerfile never sets it, and the
`?? 'http://localhost:8001'` fallback was compiled into the image. Confirmed by
grepping the shipped bundle: it contains `http://localhost:8001` and nothing
else. The runtime variable was correct, present, and ignored.

The fallback is what made it silent. Without it the build would have failed and
the defect would have been caught on the machine that built the image; with it,
the image builds clean, starts clean, reports healthy, and fails only when a
human tries to sign in.

The fix is `frontend/src/middleware.ts`, which resolves the destination per
request. That was chosen over build args because the two entrances need
different destinations while sharing one image, which is the arrangement
`docker-compose.yml` documents; baking would have forced two images. The env is
read inside the handler rather than at module scope, since module-scope access
is the shape a bundler can constant-fold — the same failure in a different
place. An unset variable now logs and returns 500 instead of defaulting.
Verified: both entrances now reach their own admin API (401 and 400 from the
backends respectively, not 500), with no ECONNREFUSED.

**A tagged server cannot sign in to its own tailnet entrance.** Testing the
bootstrap from the machine itself returns 401, and correctly so: `tag:ai-server`
was applied earlier today, `tailscale whois` for the node lists Tags and no User,
and the `Tailscale-User-Login` header `tailscale serve` injects is derived from
the connecting node's owner. A tagged node has none. The runbook said to use
"your device" without saying why the obvious first attempt cannot work, so it now
says so, and gives the loopback curl that tests the backend directly.

That curl also demonstrates §5.1 rather than describing it: adding the header by
hand to a request against `127.0.0.1:8001` authenticates as an administrator,
which is exactly why that entrance binds loopback and why a shared Docker network
with the gateway was a defect worth the network split. It also bootstrapped the
first administrator as a side effect — `users` now holds
`leolove3very@gmail.com` as `admin` in the `default` tenant, and `audit_log`
holds one `bootstrap.first_admin | success` row, which is §12's requirement
observed on a live deployment rather than in a test.

### The tailnet ACL, which the runbook never told anyone to apply

`ROADMAP.md` has carried a checked box reading "Tailscale ACL including
`tag:ntnu-proxy`, so members cannot bypass the proxy" since the architecture was
written. It described a template in `security.md` §3.4. There was no tailnet to
apply it to until today, and the runbook — which is the document that exists so
nothing gets skipped — never mentions applying it or tagging the server at all.

Following the runbook exactly therefore ends here: `sudo tailscale up` joins the
tailnet under the default policy, which for a new tailnet is
`{"src": ["*"], "dst": ["*"], "ip": ["*"]}`. Every rule in §3.4 hangs off
`tag:ai-server`, and a device that joined without `--advertise-tags` carries no
tag, so none of them matches. The failure mode is not that nothing works; it is
that everything is reachable. Any device subsequently added to the tailnet could
open `100.x.y.z:8000` or `:8002` directly and bypass every control the proxy
applies — the exact sentence §3.4 opens with, latent for as long as the tailnet
had one member and live the moment it had two.

There is a sharper consequence downstream. §8 asks the NTNU proxy administrator
to join under `tag:ntnu-proxy`, but a tag cannot be applied unless `tagOwners`
already names it. Without the ACL step, that request fails on the other person's
machine, for a reason nothing in the runbook explains.

**Applied, and then pinned.** The policy is now live on the real tailnet, and the
machine carries `tag:ai-server` with key expiry disabled — Tailscale's 180-day
default would otherwise have dropped a 24/7 server off the tailnet half a year
in. The part worth keeping is the `tests` block added to §3.4: Tailscale runs it
on every policy save and rejects a policy that fails one, so "a human member
cannot reach the data-plane ports" and "the proxy cannot reach the management
endpoints" are now assertions rather than prose. Both pass. The runbook gained
the two missing steps in the order they have to happen, since tagging before the
ACL exists cannot work.

The pattern is the same one this file recorded twice already today, and the
header warns about generally: a control that was designed, written down, marked
done, and never actually in force. The account-split test asserted nothing; the
Ollama loopback bind would not have survived a reboot; the pnpm allowlist was
inert; this ACL was a file nobody had applied. None of them looked wrong.

### GPU inference, verified at last, and two runbook steps that were quietly wrong

Runbook §3 and §4 are done, and the claim the whole machine exists for is no
longer a claim: `ollama ps` reports **100% GPU** for `qwen2.5:7b`, generating at
91.7 tok/s with prompt evaluation at 180 tok/s, at the 32768 context that
`MAX_CONTEXT_LENGTH` already configures. A container reaches it through
`host.docker.internal` and gets a completion back, so §0.1's whole bet — runtimes
native, containers calling out to them — is now measured rather than reasoned.

**A number the memory budget will want.** The model's weights are 4.7 GB and its
resident size while loaded is 6.6 GB; the difference is the KV cache at 32k
context. `MemoryBudgetService` counts only `resource_profile.memory_gb`, which is
the weights, and leaves the rest to the 20% headroom — so the headroom is
carrying about 40% of weight size per loaded model at this context on this
architecture. That ratio is not linear in model size and must not be extrapolated
to the 51.2 GB the budget currently permits, but it is the first real measurement
of the quantity §4.3 has been guessing at, and it is what the deferred
`MetricsPort` ingestion should be calibrated against.

**The runbook's Ollama service step was a silent security failure.** It said to
run `launchctl setenv OLLAMA_HOST 127.0.0.1` and then `brew services start
ollama`. `launchctl setenv` writes to the boot session domain and does not
survive a reboot, and Homebrew's plist carries no `OLLAMA_HOST` of its own — so
the first restart would drop Ollama back to its `0.0.0.0:11434` default and
publish inference to the LAN, with nothing to indicate it had happened. The bind
required by §7.1 has to survive a reboot without help, so the value now lives in
a plist committed at `launchd/online.rcsl.ollama.plist`. Two further corrections
came with it: a LaunchDaemon rather than Homebrew's LaunchAgent, because an agent
waits for a login that a headless machine after a power cut will not get; and an
explicit `UserName`, because a daemon defaults to root and would look for models
in `/var/root/.ollama` and find none. §7.1(d)'s dedicated service account is the
later hardening step, and that key is where it will land.

**§4 had a smaller version of the same gap.** It opens with `sudo tailscale up`,
but `brew install tailscale` starts no daemon, so the step fails with `failed to
connect to local Tailscale service`. `sudo brew services start tailscale` comes
first, and the `sudo` is load-bearing for the same reason it is on Ollama: it
makes the difference between a system daemon that boots and a user agent that
waits for a login.

The machine is on the tailnet at `100.108.250.62`, MagicDNS
`rcslmac1demac-studio.tail68e30b.ts.net`, and `.env` now carries that address and
the bootstrap login with no placeholders left. `tailscale serve` waits for the
frontend to exist. The only thing still blocking a first `docker compose up` is
the GeoLite2 database, which `ENV=production` with a non-empty
`ALLOWED_COUNTRIES` refuses to start without.

### The Mac Studio exists, and a test that had stopped testing anything

The deployment host is real now, and the first thing it did was falsify a claim
this file has been making for a week.

The machine is the one [ARCHITECTURE.md](./ARCHITECTURE.md) §0.2 describes: M4
Max, 64 GB unified memory, macOS 26.5. It arrived bare, so this started at
runbook §2 — Homebrew, then git, tailscale, ollama, uv, node and pnpm, then
Docker Desktop. Compose parses against the real `.env` and the real file
secrets, and the §1/§3.2 network invariant holds here as it did on the dev
machine: the intersection of the gateway's networks with each admin entrance's
is empty. `host.docker.internal` resolves from inside a container, which is the
whole of §0.1's bet that runtimes stay native.

**`test_db_role_grants.py` had been failing since 968b2ee, in the way that
hides itself.** The integration suite runs only when `TEST_DATABASE_URL` is
set, and nothing had set it since multi-tenancy landed, so the first full run
here was the first run since. The test opens with the gateway's one legitimate
write — an INSERT into `usage_records` — before asserting the six writes it
must be denied. Multi-tenancy made `usage_records.tenant_id` NOT NULL and did
not update that INSERT, so the test aborted on a constraint violation at its
first statement and **none of the six denials was ever asserted**. The same
staleness sat in the admin positive control on `users`.

The property itself is sound: with `tenant_id` supplied, all six denials pass
and the server refuses the gateway account an INSERT into `api_keys`, `users`,
`routing_policies` and `audit_log`. So this was a test defect, not a security
defect. What it cost was the evidence — and this file and `ROADMAP.md` have
both been citing that evidence by name. The multi-tenancy entry below calls the
account split "undisturbed" and reasons its way there correctly, but reasoning
is the thing the test existed to replace. This is the drift the header of this
file warns about, caught by the first machine that actually ran the suite.

**Two toolchain divergences, from the same first run.** `uv` had no
`.python-version` to read and `requires-python` says only `>=3.12`, so it built
the environment on 3.14 while `backend/Dockerfile` ships `python:3.12-slim`:
local verification and the deployed artifact were different interpreters. The
pin is now `backend/.python-version` and the suite was re-run on 3.12.
Separately, ruff 0.16.0 flags S608 on the tenant backfill's `UPDATE {table}`,
where the only interpolation is a table name from a literal tuple in the same
module and the value is bound. Suppressed inline with its reason rather than by
widening the existing per-file ignore, so it stays greppable.

Verified on this machine: 359 tests pass on Python 3.12 against a real Postgres
17 (299 unit, 60 integration — the integration half for the first time on Apple
Silicon), ruff and mypy clean over 127 files, `docker compose config` resolving
the real secrets. What still waits is everything needing the stack actually up:
GPU inference, MLX, `tailscale serve`, nginx, the GeoLite2 database, and the
live free-memory figure the memory budget is still standing in for.

**An operational note that is not a code change.** The host is configured as a
personal computer rather than a server: FileVault on, which makes auto-login
unavailable and stops an unattended reboot at the unlock screen; `pmset
autorestart` off, so it does not come back after a power cut; and Docker
Desktop's VM was sized at 8 GB against a memory budget whose 20% headroom is
meant to cover the OS, the containers *and* inference working memory. The VM is
now 4 GB. The rest is §15.6's sequencing decision and waits on the UPS.

---

## 2026-07-25

### Logs UI and usage charts, and a chart library chosen by not choosing one (Phase 2)

Two frontend Phase 2 items, both needing a backend read path first. Neither the
audit log nor the usage table had one: auditing was write-only (its adapter
commits each row in its own transaction so a failed request still leaves a
trail), and usage had only the dashboard's 24-hour totals. So the work is a
read path on each, then the screens.

**The audit read is an ordinary scoped query, kept away from the writer.** A new
`AuditEntry` entity and `PostgresAuditLogRepository` read the append-only table on
the request session, tenant-scoped by the same `_scope` helper every other read
uses, with `ReadAuditLog` behind `logs:read` (a scope that already existed in the
enum, unused until now). The write side stays on `AuditPort` and its independent
transaction: reading must not borrow that machinery. The page is bounded (a
default 50, a hard 200) because an operator UI never needs the whole table and an
unbounded limit is a memory lever on a table that only grows. The frontend
`features/logs` is server-paged rather than a client-side table over one fetch,
for the same reason, with action and outcome filters that reset to the first page
so an offset cannot point past a smaller filtered set.

**Usage analytics reads the accounting table, which is not what Grafana shows.**
The distinction from the observability commit earlier today matters: Prometheus
reports live operational state to an operator over Grafana; this reads
`usage_records`, per tenant, for the management UI. Different audience, data, and
access path. A `date_trunc` aggregation (`bucketed_usage`) groups by time bucket
and capability in one query, and `ReadUsageAnalytics` (behind `usage:read_all`,
the scope the dashboard totals already use) folds the rows into per-bucket totals
and per-capability series. The window is a small closed set (24h, 7d, 30d) that
fixes the bucket granularity with it, so the query's cardinality is bounded and
the range picker maps to exactly three shapes; time comes from an injected clock
so the windowing is testable.

**The chart-library question, which the codebase had deliberately deferred, is
settled: no library.** The `MetricChart` placeholder had recorded the open
decision (Tremor had shifted to copy-in source with the §10 supply-chain caveat;
Recharts was the fallback but a real dependency with a React 19 version
constraint). The data these screens show is simple magnitude-over-time, so the
charts are inline SVG instead: a component that draws lines and an area with axes
and a hover tooltip, and the pure geometry (scales, path building, nice-max
rounding) in `chart-geometry.ts` where it is unit-tested with no DOM. Series
colours read the theme's computed `--chart-1..5` ramp through `currentColor`, so
they follow light and dark without a second palette. The trade is that axes and
the tooltip are ours to maintain; that is acceptable while the charts stay simple
time series, and a richer visualisation would be the point to revisit it. One
series renders as a filled area, several as plain lines with a legend.

The dashboard's two chart placeholders now carry real 24-hour data from the same
endpoint, and its note no longer promises Phase 2: it points at usage records for
counts and at Grafana for the live operational metrics.

Verified: 6 new backend unit tests (the two use cases' authorization, the page
clamp, and the fold from buckets into totals and per-capability series) and 3
integration tests against real Postgres (the audit read's tenant isolation and
newest-first ordering, and that `date_trunc` buckets by hour and capability while
excluding another tenant's rows); the full backend suite passes, mypy and ruff
are clean. On the frontend, 9 new tests (the chart geometry and the two response
schemas), `pnpm test`, `eslint`, and `next build` with the `/logs` and `/usage`
routes generating. One small structural consequence worth noting: extending
`UsageRepositoryPort` with `bucketed_usage` meant the `MeteredUsageRepository`
decorator from this morning had to delegate it too, which mypy caught rather than
leaving for runtime.

### Observability: the emission side, and the word "metrics" pulled apart (Phase 2)

The Phase 2 item read "MetricsPort with Prometheus and Grafana; live metrics
replace the static memory budget," and the first useful thing was noticing it
conflates two different things the codebase already keeps apart. There is a
`MetricsPort` in the domain, and it is the *ingestion* side: `free_memory_gb`, a
live hardware figure the memory budget would consult instead of static capacity.
And there is the thing every deployment actually wants first, the *emission*
side: the process exposing what it is doing so Prometheus can scrape it. This
change ships emission in full. The ingestion half stays deferred on purpose,
because a real free-memory number for the node exists only on the Mac Studio, and
`security.md` §4.3 already says the budget must not wait on metrics: so the budget
stays static and authoritative until the figure is real, which is the
conservative reading of that rule rather than a gap.

**The instruments are derived from what the code already produces, so the
delicate paths are untouched.** HTTP series (request count, duration, in-flight)
come from one pure-ASGI middleware. Pure ASGI rather than `BaseHTTPMiddleware`
because the gateway's reason for being is streaming, and `BaseHTTPMiddleware`
returns once the response object exists, which for an SSE stream is before a
single token has gone out: timing and the in-flight gauge would measure
time-to-first-byte, not the duration a request actually occupied a slot. Wrapping
`send` and recording when the response truly finishes fixes both. Inference series
(tokens, completion outcome, duration by capability and model) come from a
`MeteredUsageRepository` that wraps the usage repository and reads the same
`UsageRecord` the streaming use case already writes in its `finally` — so
`RouteChatRequest`, the most carefully ordered file in the tree, gains observation
without a line of instrumentation in it. The concurrency-slot gauge is read from
the live limiter at scrape time rather than tracked through the request path, so
it cannot drift out of step with the semaphore it reports.

**The route label is a template, never the raw path.** An id in a URL would make
each request its own time series, and a port scanner hammering 404s would turn
unbounded cardinality into a memory problem. The middleware reconstructs the
matched template from the router's path params and collapses anything unmatched to
a single `__unmatched__` label. No label carries a caller identity, tenant, or
key, for the same reason and because the exposition body is an information
disclosure if it ever leaks.

**Which is why /metrics is guarded, not merely placed on an internal network.**
The gateway carries `/metrics` on the same ASGI app that faces the proxy, so
network placement alone would rest on the operator's nginx being precise forever.
The endpoint requires a bearer token from a file secret — the same shared-secret
pattern the trusted-proxy check already uses — and returns 404, not 401, without
it, so a caller does not even learn it exists. On the admin entrances `/metrics`
is exempted from the geo/proxy perimeter (like health) so Prometheus can scrape
over the internal network; the token is the actual control there. Placeholder
tokens are refused in production exactly like the other secrets, but only when
metrics are enabled, so a deployment that runs no Prometheus is not forced to
invent one.

**Scraping does not reopen the gateway/admin isolation.** Prometheus scrapes all
three apps, so it sits on both a gateway-side scrape network and an admin-side
one, but the gateway and the admin entrances still share no network with each
other, which is the §1/§3.2 invariant (`docker compose config` confirms the
intersection is empty). The only node on both is Prometheus, and unlike Postgres
and Redis — also dual-homed but never initiating — Prometheus does initiate. What
makes it safe is that it is a scraper, not a forwarding proxy: it issues only the
fixed `GET /metrics` requests in its config, so a compromised gateway cannot use
it to reach an admin entrance. Grafana is on the Prometheus network only, binds
loopback, and is reached over `tailscale serve`; Prometheus publishes no port.
Grafana's default `admin`/`admin` is replaced from a file secret, with anonymous
access and self-registration off, which is the §6 requirement that had been
sitting unactioned.

Verified: 18 new unit tests (the token guard returning 404 on all three apps, the
disabled-endpoint case, a served request counted under its template, the slot
ceiling reported, a scanner's paths collapsing to `__unmatched__`, the label
reconstruction, and the metered repository emitting from a record while still
persisting it); the full unit suite at 290 passing; ruff and mypy clean; and
`docker compose config` renders with the network invariant intact. What waits for
the Mac Studio is what always does: real scrape traffic, and the ingestion figure
that would let the budget go live. The two dependent Phase 2 items, the logs UI
and in-app usage charts, are unstarted; Grafana covers the metrics view for now.

### mypy made honest, and put where it cannot drift again

Running `mypy app` over the whole package, which this log had repeatedly called
clean, turned up 24 errors. Two things had been hiding them.

There was no automation. pre-commit ran gitleaks and ruff but never mypy, and
there is no CI, so "mypy clean" was an impression from running it by hand on
whichever module was just written, never the whole package at once.

And the config's relaxation was inert. A block declared `strict = false` for
`app.adapters.*`, on the reasoning that adapters wrap third-party libraries with
incomplete stubs. But mypy silently ignores `strict` in a per-module override:
it is a global-only meta-flag, so the adapters were strict-checked the entire
time, and the comment describing them as relaxed was describing something that
was not happening.

The one error worth calling a defect rather than noise was a contract lie. Both
runtime adapters typed `generate` and `pull` as returning `AsyncIterator`, while
`ModelRuntimePort` promises `AsyncGenerator`. `AsyncIterator` is the wider type
and does not guarantee `aclose()`, which is the exact promise the port's own
docstring spends a paragraph on, because that promise is the streaming contract:
without it a disconnected client leaves the runtime generating and the slot held.
The behaviour was correct (an `async def` with `yield` is an async generator), but
the annotation was weaker than the code, and it was the mismatch mypy flagged at
`di.py` as the adapters not satisfying the port. Aligning the annotations closed
that and the port-conformance errors together.

The rest were ordinary: a missing `target: Model` and three unannotated function
parameters, a response-variable that needed widening to `Response`, and a
`type: ignore` that no longer suppressed anything. Genuine third-party stub gaps
(SQLAlchemy typing async `execute` as `Result`, which lacks `rowcount`; redis
returning `str` under `decode_responses=True` but typed `bytes | str | None`;
huggingface_hub not exporting two error classes) are pinned with targeted casts
and `type: ignore` at the call site, where they are visible and greppable, rather
than a blanket relaxation that would hide real errors alongside them. The inert
override is gone, replaced by a comment recording why it never worked.

To stop the drift recurring, a local pre-commit hook now runs
`uv run --directory backend mypy app` on any change under `backend/app`. Local
rather than mirrors-mypy so it type-checks against the project's real resolved
dependencies instead of a hand-maintained second copy, and whole-package because
mypy's cross-module inference is what makes it accurate.

One change surfaced a latent issue. Giving `chat_completions` a return annotation
(`ChatCompletionResponse | StreamingResponse`) made FastAPI try to build a
response model from a union containing a `Response`, which it cannot; the fix is
the documented `response_model=None`. It was caught immediately by the unit tests
that load the gateway app, not left for deploy, which is the payoff of the
annotation existing at all. Verified: `mypy app` reports no issues over 118 files,
ruff is clean, and 272 unit tests pass.

### The last resource guardrail: a wall-clock generation deadline

Auditing ROADMAP §120 against the code found the item mislabelled rather than
missing. Of the four guardrails it lists, three were already built and wired:
the concurrency cap (`SemaphoreConcurrencyLimiter`, held for the whole generator
in `RouteChatRequest`), the `max_tokens` output ceiling (min of the caller's
request and our cap, pushed to Ollama's `num_predict` so the model stops at the
source), and cancel on disconnect (`aclosing` throughout, so the adapter closes
its upstream HTTP request). A fourth, the per-request context bound, was wired
too, closing the `max_context_length` setting that an earlier review had flagged
as configured and read by nothing. Only "timeout" was partial: the adapter has a
per-read HTTP timeout, but nothing bounded the total wall-clock time of a
generation.

That gap is narrow but real. The token ceiling bounds a stream producing at a
healthy pace, and the per-read timeout bounds a stalled one (no bytes for the
interval). The uncovered case is a stream that keeps producing slowly enough to
stay under the read timeout yet never reaches the token cap, which on unified
memory near swap can hold one of only two concurrency slots for hours. With no
edge protection that is a genuine, if edge, denial-of-service lever.

So `RouteChatRequest._generate` now checks a wall-clock deadline in the yield
loop and cuts the stream with `finish_reason=length`, the same honest signal the
token-ceiling truncation already uses, so an OpenAI client is not told the model
finished. The deadline is `generation_deadline_seconds` (default 600, zero or
negative disables it, matching the heartbeat convention). Elapsed time comes from
an injected `monotonic` callable rather than the wall-clock `Clock`, for two
reasons: an NTP step must not move a live generation's deadline, and the seam
lets the deadline be tested without any real waiting. Two unit tests drive it: a
slow runtime that advances the injected clock ten seconds per token trips a 25s
deadline after three tokens and releases its slot, and a zero deadline falls back
to the token ceiling. 272 unit tests pass; ruff is clean and mypy shows no new
errors over the pre-existing baseline.

What waits for the Mac Studio is the same boundary inference has always had: the
guardrail's arithmetic and the truncation contract are exercised now against an
injected clock, but a real slow generation on the GPU is only observable there.
The pre-launch checklist item in security.md §14 that says to verify the
guardrails in practice still stands.

### Multi-tenancy, the isolation boundary made real (Phase 2)

The third Phase 2 item, and the most invasive: the platform was single tenant and
said so, and this makes the boundary exist. Every `users`, `api_keys`,
`usage_records` and `audit_log` row now carries a `tenant_id`, a migration
backfilled the existing rows into one default tenant, and the tenant-scoped
repositories filter every read and stamp every write by it.

**The filter lives in the adapter and is taken from the actor, never the caller,
which is the whole of section 7.3.** A tenant-scoped repository is constructed
with a tenant id, and the di builder takes that id from the authenticated actor
(`users.tenant_id` on the admin entrances, `api_keys.tenant_id` on the gateway),
so a use case receives an already-scoped repository and cannot read another
tenant's rows or forget to say which tenant it means. The use cases themselves
barely changed, which is the payoff: the boundary is structural, not something
each handler remembers. A scoped read adds `WHERE tenant_id = :t`; a scoped write
stamps the repository's tenant onto the row regardless of what the entity carried;
and the targeted updates (revoke, disable, edit) carry the tenant into their
`WHERE`, so a scoped operation cannot touch another tenant's row even by its id.
The integration test proves all of this against a real Postgres, which the unit
fakes cannot, because they have no filter to enforce.

**A few paths are deliberately unscoped, and each resolves a principal before any
tenant is known.** Authentication looks a user up by a globally-unique login, the
session resolver looks one up by id, the gateway looks a key up by its handle, and
bootstrap counts every user platform-wide. Reading exactly the one row a unique
handle names is not a cross-tenant enumeration, and the tenant is then read from
that row. These use an explicit `.unscoped()` repository, so the choice is visible
and greppable rather than a forgotten default.

**A review of these three Phase 2 commits caught where the scoping went one step
too far.** The invite flow's duplicate-login check had been left on the
tenant-scoped repository, but a login is a platform-global namespace: `users.login`
is globally unique, so a login already taken in another tenant would slip past a
scoped check and fail at the unique constraint as a bare 500 rather than the clean
409 the check exists to give. `get_by_login` is now never tenant-scoped, for the
same reason authentication resolves it globally: it answers only "does this login
exist anywhere", and the row it returns carries its own tenant. The review's other
findings were hygiene rather than logic: a docstring displaced onto the wrong
field, a stray UTF-8 BOM and mangled em-dashes that a scripted `.unscoped()` edit
had left in four integration test files, an unhandled promise rejection in the
tenant-create dialog, and a duplicated onboarding-link builder now shared between
the users and tenants routers.

**Shared infrastructure stays platform-global.** `models`, `nodes` and
`routing_policies` are the compute the tenants share (one loaded model serves
everyone), so they carry no tenant and are managed by any admin. Tenants
themselves are platform-global too: managing them is an admin operation, not
tenant data.

**Minimal but usable tenant management.** `ManageTenants` creates a tenant and,
in the same call, mints its first administrator's invitation into that new tenant
(a tenant with no admin cannot be populated), and lists tenants. The ordinary user
invite lands in the inviting admin's own tenant, stamped by the scoped repository.
There is no platform-super-admin versus tenant-admin split yet: admins are
platform-trusted, which suits a single research centre, and the stricter hierarchy
can follow if a genuinely external tenant appears. The knowledge base, the main
tenant-scoped consumer, is not built yet; it plugs into this boundary when it is.

One structural change made it clean: `current_actor` and `current_session` moved
from the identity middleware into `di.py`, so the scoped-repository builders can
depend on the actor without the middleware and the composition root importing each
other in a cycle. The middleware re-exports both, so routers and the entrance apps
are untouched.

Verified: the migration round-trips (it seeds and backfills the default tenant, so
the column is NOT NULL with no data-migration window); the account split is
undisturbed (the gateway's schema-wide SELECT already covers the new table, and it
still has no write on `api_keys`, `users` or `tenants`); 270 unit tests pass, with
four new for `ManageTenants` and a five-case integration test pinning the isolation
property against real Postgres; ruff and mypy are clean on the new code; and the
frontend gained a `features/tenants` screen (list plus a create dialog that shows
the first admin's one-time link) through `tsc`, `eslint` and `next build`.

### Node management, and the SSRF guard that had to ship with it (Phase 2)

The second Phase 2 item, and the one the security document had been holding a
rule over: a node write endpoint may exist only if the SSRF guard ships with it,
because a node's `address` is a value the platform makes outbound requests to,
and an attacker who can register `169.254.169.254` or `127.0.0.1` has turned node
management into internal probing (§7.2). Until now the rule was satisfied by the
absence of a write path: the single node was seeded from configuration and no
endpoint accepted an address. This change adds the write path and the guard
together.

**The guard is the core, and it validates on the way in, not only on the way
out.** `adapters/http/egress_guard.py` resolves an address and requires every
result inside the tailnet range (`100.64.0.0/10` and the Tailscale IPv6 ULA).
One range is the whole rule: loopback, link-local, the RFC 1918 LAN, and the
cloud metadata endpoint are all outside it, so none has to be enumerated. A
literal IP is checked without a DNS lookup, which also means the value stored is
the value connected to; a hostname is resolved and rejected if any answer falls
outside the tailnet, so a name that resolves partly off-net cannot pass on the
strength of one good record. The check runs at every node write, so an address
that could never be reached safely is refused before it is stored rather than
surfacing later as a failed probe. It reaches the use case through
`EgressGuardPort`, not a direct import, the same discipline that keeps
model-reference validation off the application layer.

**Status stopped being an assumption.** Phase 1 wrote every node `online` at
provision and never looked again, which made a routing requirement of
`node_status: [online]` inert, since it always held. A `NodeHealthPort` now
observes status by probing the runtimes a node declares (online when all answer,
degraded when some do, offline when none does or none can be probed), and a
heartbeat in the admin application runs it on an interval. So a policy that
demands an online node actually stops routing to one whose runtime has gone away.
The heartbeat runs in the admin app rather than the gateway because the §6
least-privilege split lets the gateway write only `usage_records`, never
`nodes`; both admin entrances run it, which is why the write is a targeted,
idempotent `set_status` and why a status is written only when it changed. The
loop sleeps before its first sweep, so the many tests that open and close the
admin lifespan cancel it before it ever touches the database. Single-node scope
is stated plainly in the adapter: the runtime adapters point at the configured
host runtime, so the probe is accurate for the one node they can reach and a
second node will need per-node runtime endpoints, deferred with multi-node.

**Deletion is guarded too.** `models.node_id` is a foreign key, so deleting a
node with models attached would fail as an IntegrityError at flush, which in
FastAPI is after the response has gone and has nowhere to report. The use case
refuses it first, naming the models, and the same shape gives a duplicate node
name a clean 409 instead of a unique-violation 500, matching how `ManageModels`
already reports a taken alias. Registration and removal are audited, as §12
requires.

`GET /nodes` moved from the models router to a new `routers/nodes.py` carrying
the full lifecycle: the read the model form needs plus register, edit, delete,
and an explicit health check for the UI's refresh action. The frontend gained a
`features/nodes` management screen (table with live status, a create/edit form
whose address field is validated server-side, delete, and check-now) and a nav
entry. The stale "node management is Phase 1 read-only" comments across the
models feature were corrected rather than left to mislead.

Verified: 27 new backend tests (the egress guard against loopback, LAN, metadata
and rebinding; `ManageNodes` for the guard running before a store, the
attached-models delete refusal, status as the probe's observation; the heartbeat
writing only changed statuses), the full unit suite at 266 passing, ruff and
mypy clean on the new code, and the frontend through `tsc`, `eslint`, and
`next build` with the `/nodes` route generating. Real probing of a runtime still
waits for the Mac Studio, the same boundary inference has; the guard, the write
rules, and the heartbeat's change-detection are exercised now.

### The second runtime adapter, which is the real test of the layering (Phase 2)

The first Phase 2 item, and the one worth doing first because it answers a
question the rest of Phase 2 assumes: did the hexagonal layering actually buy
what it was chosen for. The stated pass criterion was that adding a runtime
touches no use case and no interface. It held. The diff is one adapter file
(`adapters/runtime/mlx_adapter.py`), its per-runtime reference grammar
(`adapters/runtime/hf_validation.py`), and three wiring points: one entry in
`build_runtimes`, one setting, one Compose mount. `application/use_cases` and
`interfaces` are untouched, and the domain is too, because `RuntimeKind.MLX`
already existed. `route_chat_request` resolves the adapter from the model's
`runtime` field through the same dict it always did.

The value of the exercise was less the wiring than the three places MLX is
genuinely unlike Ollama, each of which the port absorbed without bending, but
only after a real decision.

**MLX has no download-with-progress endpoint, and its download lands somewhere
Ollama's never had to.** Ollama's daemon pulls on the host and streams NDJSON
progress back, so the adapter only relays. MLX models are HuggingFace snapshots
and `mlx_lm.server` downloads them lazily with no progress stream. So `pull`
here does the download itself, via `huggingface_hub` in a worker thread, and
reports real byte progress by polling the cache while it runs. The subtlety that
forced a decision: a download run inside the container would land in the
container filesystem, which the host-native server cannot read. The bytes have
to reach the host cache. So HF_HOME is a bind mount onto the host's HuggingFace
cache, and this is the one place in the deployment a container writes to a host
path. That does not contradict the section 0.1 rule that runtimes are not
containers: the rule is about GPU and compute, and a snapshot download is file
I/O whose only constraint is where the bytes end up.

**`mlx_lm.server` has no unload, so `unload` refuses rather than lying.**
Reporting success would move the registry to DOWNLOADED while the weights are
still resident on the host, and the memory budget would then stop counting a
model that is still occupying memory, admitting a later load that should be
refused. That is precisely the unified-memory over-commit the section 4.3 budget
exists to prevent. The adapter raises `ModelStateConflictError`, and
`ManageModels.unload` already does the right thing with it: the model is left
LOADED, which is the truthful state, and the operator gets a 409 that says the
runtime cannot evict. A silent no-op would have been the dangerous option, not
the convenient one.

**The token count is only authoritative at the end**, in the terminal usage
frame, exactly like Ollama's `eval_count`. Chunks are counted one apiece as they
stream so a disconnect still bills what was produced, and the final frame emits
only the difference rather than the whole figure, which would double-count.

The reference grammar is per-adapter, as `ModelRuntimePort.validate_ref` intends:
a HuggingFace repository id, not Ollama's `namespace/name:tag`. It rejects `..`
and anything that is not a plain repo id at the boundary, because the value
reaches `snapshot_download(repo_id=...)` and a repo id carrying path traversal
is the section 7.1 concern in a different runtime's clothing.

Verified with 12 port-conformance tests against a stubbed transport and stubbed
download seams, no MLX and no GPU in the loop: the OpenAI SSE stream maps to
`CompletionChunk` and reconciles the token total, the upstream request is closed
on client disconnect (the guarantee the streaming contract rests on), a bad
reference is rejected before any network call, a stream that ends without a
terminal frame raises rather than reporting a clean stop, `unload` refuses
without touching the network, and `pull` climbs monotonically from starting to
success. The full unit suite is 237 passing; ruff and mypy are clean.
`huggingface_hub` is imported lazily inside the download seams only, so the
inference path neither pays its import cost nor depends on the library being
present, and the mypy override mirrors the existing zxcvbn one.

What waits for the Mac Studio is real MLX inference and a real download, which
need Apple Silicon and cannot run on the Windows dev machine, the same boundary
Ollama inference has always had. The architecture claim itself does not wait for
that: it is the zero use-case, zero-interface diff plus the port-conformance
suite, and both are done now.

### A production smoke test on the dev machine, which moved the deploy risk down

Ran the whole stack once on Windows under `ENV=production` with generated
(non-placeholder) file secrets, which exercises the Compose wiring the account
split had only been structurally checked against. It held: `migrate` exited 0
having run the migrations and logged `database roles provisioned:
nexus_gateway(gateway), nexus_admin(admin)`, so `db_roles` created both roles
from the mounted URL secrets and applied their grants in the real flow. All
eight containers came up; postgres, redis and the gateway reported healthy, and
`/readyz` returned 200 on the gateway and both admin entrances. `pg_stat_activity`
showed the gateway connected as `nexus_gateway`, not the owner. And the boundary
is enforced by the deployed database, not just by the earlier unit and
integration tests: as `nexus_gateway`, `SELECT api_keys` and an `INSERT` into
`usage_records` both succeed, while `INSERT INTO api_keys` is refused with
`permission denied for table api_keys`.

What this does not cover, and still waits for the Mac Studio: the country filter
(run with `ALLOWED_COUNTRIES` empty, since there is no GeoLite2 database here),
GPU inference, `tailscale serve`, and nginx. The production config validators,
the role provisioning, the per-account connections, and the grant enforcement
are no longer first-run risks.

### A first-deploy runbook, and the GeoLite2 mount it turned up

Compiling the Mac Studio pre-deploy checklist ([runbooks/first-deploy.md](./runbooks/first-deploy.md))
surfaced a blocker: the Compose file mounted no `/data` into the backend
services, but `build_geo_filter` refuses to start in production when
`ALLOWED_COUNTRIES` is set and the GeoLite2 database is missing. So the stack as
written would have failed to boot on the first real deploy. The `x-backend`
anchor now bind-mounts `./data` read-only, and the runbook step is to drop
`GeoLite2-Country.mmdb` there. The runbook is written for someone who has not
used macOS: first boot, Homebrew, Docker Desktop, native Ollama bound to
loopback, Tailscale and `tailscale serve`, the secrets, and the §14 checks that
must be tested rather than assumed.

### The database account split, and secrets moved to file mounts

The last functional-to-operational Phase 1 item, and the deeper half of the
defence the network split (§15.5) only started. Until now every backend service
connected as one account that owns the schema, so a compromised gateway that
could not reach the admin socket could still write `api_keys` and mint itself a
key. Now there are three Postgres accounts: the gateway reads every table and
writes only `usage_records`; the two admin entrances share an account with full
DML and no DDL; the owner holds DDL and is used only by `migrate`.

The roles are provisioned in code (`infrastructure/db_roles.py`), run by the
`migrate` job after the schema exists. Three decisions carried it.

The grants are **declarative, not additive**: the gateway's table privileges
are revoked and re-granted on every deploy, so its writable set is always
exactly `GATEWAY_WRITABLE_TABLES` regardless of what a previous run left, and a
table added by a later migration is regranted without anyone editing SQL. The
one writable table is named in code, where it is under review, rather than in a
deployment file.

The account **name is taken from each service's own connection URL**, so the
URL secret is the single source of truth for both the name and the password;
this module never invents a name the deployment did not commit to. `migrate`
connects as the owner and reads the gateway and admin URLs to create those two
roles.

And the SQL is **built as text with hand-quoted identifiers and literals**,
because `GRANT`, `CREATE ROLE`, and a role password are DDL that no driver
parameterises. The quoting helpers are the standard minimal escapers, safe
under `standard_conforming_strings`; role names are additionally constrained to
a strict pattern because a name is an identifier we control. `exec_driver_sql`
rather than `text()` runs them, so a colon in a generated password is not read
as a bind parameter. Ten unit tests pin the security property directly: the
gateway is granted no write anywhere but `usage_records`.

Alongside it, secrets moved from `env_file` to Docker **file mounts**. This was
forced by the split as much as chosen: an environment variable outranks a file
secret in pydantic-settings, so a value left in `.env` would silently override
the mounted one. `.env` now carries only non-secret configuration; every
credential is a file under `./secrets` (git-ignored, with `.example` templates
and a README), mounted at `/run/secrets` and read through `secrets_dir`. Each
service mounts only what its role needs, except that the four crypto secrets go
to `migrate` too, because it calls `get_settings()` and production refuses the
placeholders. Postgres reads its password through `POSTGRES_PASSWORD_FILE`;
redis, which has no such convention, reads the file in its command.

**What is verified, and what waits for the deploy.** The security property
itself is now proven against a live Postgres 17: an integration test
(`tests/integration/test_db_role_grants.py`) provisions the two roles the way
`migrate` does and asserts the server refuses the gateway account an INSERT into
`api_keys`, `users`, `routing_policies` and `audit_log`, while keeping its reads
and its `usage_records` write, with the admin account as the positive control.
`docker compose config` resolves the secret mounts as intended and the unit
suite passes. What still waits for the Mac Studio is the full compose wiring end
to end: `migrate` creating the roles from the mounted URL secrets, and each
service connecting as its own account rather than the single-account
`AUTH_MODE=dev` default the Windows machine uses.

### A routing policy editor, so the one thing that makes the gateway serve is no longer curl-only

The routing policy API was complete and audited but had no screen, so the
single thing that decides what the gateway serves for a capability was
configured by hand. `features/routing-policies` now carries a table (one row
per capability, candidates summarised highest-priority-first to match how the
gateway evaluates) and a candidate editor: a `useFieldArray` over the candidate
list, each with a model alias, a priority, and the structured requirement as
checkbox groups over node status and model state plus an optional free-memory
floor.

Three decisions worth the note. The requirement stays a closed set of
structured fields rather than an expression box, exactly as the domain demands
(ARCHITECTURE.md section 2.4): the same reason the backend refuses one is the
reason the form does not offer one. Creating a policy is only offered for
capabilities that do not already have one, because a save is a full replacement
keyed by capability (`PUT`) and a "create" over an existing capability would
silently overwrite it. And the memory floor is backed by a text input where a
blank field means "no floor" and becomes null, kept out of a plain
`z.coerce.number()` because coercing an empty string yields zero, which would
read as a real 0 GB requirement rather than the absence of one; the schema test
pins that.

The response schemas parse against the same enums the models feature uses, so a
node status or model state the frontend does not know surfaces as a parse
failure rather than a candidate that silently never matches. Verified through
`tsc`, `eslint`, `next build` (the `/routing-policies` route generates), and ten
new schema tests.

### A frontend test runner, on the units where a defect is a security defect

The one Phase 1 gap most worth closing first, because the type checker had been
the only gate and two of the three defects it let through were security
defects. Vitest with jsdom, and 44 tests over the pure logic the adversarial
review had already found holes in: `safe-redirect` (the backslash open-redirect
that survives a prefix check), the chat SSE schema and reader (the OpenAI
envelope that an earlier flat schema silently stripped to nothing, plus the
error, malformed, truncation and abort frames), `api-client` (the CSRF header
attached only on mutations and only when the cookie is present, the 401 that
becomes an `UnauthorizedError` and an event, and the absence of any
`Authorization` header), and the password schema's length-and-strength
threshold.

Two decisions worth the note. The `@/` alias is resolved in `vitest.config.ts`
directly rather than through a tsconfig-reading plugin, so the test setup does
not depend on how that plugin parses config. And the jsdom environment runs on
`https://localhost/` because the CSRF cookie carries the `__Host-` prefix,
which jsdom's cookie jar correctly refuses to store over http, so a test on
http would have been asserting against a control that the browser also drops.
The test files are excluded from `tsconfig.json` so `next build` does not try
to type-check them.

What is not covered: nothing renders a component or drives a browser yet. The
sign-in and enrolment screens, which are the surface where a defect is a
security defect, are still only reachable through their schemas and hooks in
these tests. Playwright is the deferred increment, recorded in `ROADMAP.md`
Phase 3.

### Closed the network exposure the review left standing

The sharpest finding, recorded as accepted risk §15.5, is now fixed rather than
carried. The gateway and the tailnet admin entrance shared the `app` Compose
network, and the tailnet entrance trusts `Tailscale-User-Login` outright, so a
compromised gateway could reach `admin-tailnet:8001` by service name and forge
an administrator. Socket binding, the design's stated isolation, protects the
host-published port but not the Docker service name.

The single `app` network is split so the gateway shares none with either admin
entrance. The data plane gets `gateway-data` (internal, for postgres and redis)
and `gateway-egress` (for the host runtime); the control plane gets `admin-data`
and a per-entrance control network carrying the frontend and its admin API.
postgres and redis are the only members of both database segments, which is
safe because they accept connections and never open one — a shared datastore is
not a shared path. The same split also stops the internet-facing public frontend
from reaching the tailnet entrance.

The invariant is not a comment but something `docker compose config` can be
asked: the intersection of the gateway's networks with each admin entrance's is
empty. What remains open is the deeper §6 defence, per-service database
credentials, so a compromised gateway cannot read or write the control plane's
tables; the forged-header path specifically is gone.

### Five adversarial reviews, and the twenty-eight defects they found

The admin API was attacked by five independent reviews, each on one surface:
authentication and sessions, authorization and data exposure, persistence and
concurrency, the model lifecycle and jobs, and the frontend/backend contract.
Their findings were verified before acting, and the verification mattered:
several passed against the in-memory fakes while being wrong in Postgres, and
one review's headline claim needed a real database to confirm.

Most of these were introduced by the two admin-API commits above. The fixes
are in four commits after this one; what follows is why they existed.

**Four defects made the system unusable.** Every admin call 404'd, because the
Next.js rewrite keeps the `/admin` prefix and the routers mounted at the root;
nothing caught it because every test called the ASGI app directly, so they
exercised handlers and never the contract. No API key could be issued, because
the expiry field is an `<input type="date">` that sends a naive datetime and
comparing it to an aware `now` raised `TypeError`, a bare 500. Both create
paths destroyed their one-time secret, returning the unsaved entity whose
`created_at` is null, which the frontend's parse rejects after the row exists,
taking the plaintext key and the invitation link with it. And a compromised
gateway could authenticate as an administrator: it shared the `app` Docker
network with `admin-tailnet`, which binds `0.0.0.0` and trusts
`Tailscale-User-Login` outright, so §5.1's "isolation by socket binding" held
for the host-published port but not the bridge. (Closed since, by the network
split described in the entry above.) That last one is the sharpest lesson:
making the tailnet entrance a full API is what opened it, and it was invisible
while the entrance mounted only health.

**Controls the design claimed and the code did not deliver.** The login
throttle refused on a per-account count alone, which is the hard lockout §5.3
forbids because it is a denial-of-service lever against a named person, and a
successful login cleared the per-address counter so one valid account could
reset it. A `user` could mint an unmetered gateway key, because the gateway
reads `rate_limit_rpm <= 0` as no limit and quota zero as no quota, and expiry
had no upper bound. The country filter was absent from the public admin
entrance while four places said it was present, one of them a router comment.
CSRF was absent from the tailnet entrance on the false premise that it has no
ambient credential, when `tailscale serve` attaches the identity header to any
request a hostile page can provoke.

**State and data corruption.** A failed load wrote `error` and then raised,
and the raise rolled the write back, so a half-resident model read as
`downloaded` and the budget under-counted it. The three transient states were
permanent dead ends after a crash, escapable only by SQL. The download task
held one transaction open for the whole multi-hour pull. Two full-row `save`
calls could revert a concurrent revoke or disable. Each of these had a passing
test that used an in-memory fake with no transaction and no row lock, which is
why the new coverage runs against real Postgres.

The lower-severity findings — a `user` role wider than §5.2, a challenge that
outlived a disable, two CSRF paths that 500'd, `GET /api-keys` loading full
user entities, a double SSE terminal frame — are in the fourth fix commit.

**What was checked and found sound, so it is worth recording as tested:**
session fixation and the watermark invalidation, TOTP replay across every skew
case, the bootstrap atomicity, enumeration resistance, the model-reference
grammar (`fullmatch` closes the trailing-newline hole and the registry
allowlist rejects `hf.co.evil.com`), the streaming slot released within a
millisecond of disconnect, and the migrations round-tripping with zero ORM
drift.

**Residual items, accepted or deferred rather than fixed:**

- **Commit-after-response.** FastAPI commits the request transaction after the
  response is sent, so a create returns `201` with the body before the INSERT
  is attempted; a constraint violation then has nowhere to report. The
  narrow trigger is a TOCTOU on a uniqueness check under concurrent identical
  creates. Structural to how the yield-dependency session works; not changed.
- **A model stuck in a transient state by a bare container crash** (not a
  `compose` restart) is reconciled only at the next deploy, because
  provisioning runs in the `migrate` service. `restart: unless-stopped`
  brings the container back without re-running it.
- **The concurrent-load budget race** is narrowed, not closed: `LOADING` is
  now committed independently and counted, so the window is milliseconds
  rather than the whole load, but two loads landing in that window can still
  both pass. A node advisory lock would close it and is deferred.
- **`session_signing_key`** is enforced as a production secret and read by
  nothing: sessions are opaque Redis ids by design. Left in place, noted here.

### The rest of the admin API

Models and their lifecycle, downloads as background jobs, routing policies,
API keys, the remainder of `/users`, the dashboard, and `/admin/chat`. An
integration test now walks Phase 1's stated goal in one sequence: register a
model, bind a routing policy to it, issue a key, and read the dashboard back.

**A gap that only appeared once the endpoints existed: nothing could create a
node.** Models attach to one, and `security.md` §7.2 says a node write
endpoint must ship with the SSRF guard, because a node record is an address
the platform will then make outbound requests to. So a fresh deployment could
register nothing at all. Phase 1 is single-node by definition, so the node is
named in configuration and written at admin start instead. That keeps the rule
intact rather than working around it: nothing accepts an address from a
caller, and the write endpoint still waits for the guard.

**`last_used_at` is derived, not stored.** The frontend wanted the column, and
maintaining one would mean the gateway writing to `api_keys` on every request
— which is precisely what the least-privilege split in §6 exists to prevent.
The same fact is already in `usage_records`, written by the account that
should write it and indexed on `(api_key_id, at)`, so it is one aggregate at
list time. The dashboard's 24-hour figures come from there too; the frontend
schema had them as Phase 2, but Phase 2 is live metrics from Prometheus, and
request and token counts have been in the database since Phase 1.

**Model reference validation moved onto the port.** Registering a model needed
the same check the Ollama adapter already performs, and importing it into the
application layer would have been the layering violation fixed a day earlier.
Putting it on `ModelRuntimePort` is the better answer anyway: what counts as a
reference differs by runtime. Ollama takes `namespace/name:tag` from a small
set of registries, MLX takes a HuggingFace repository id, vLLM will take a
path. A shared helper would have to be the union of all of them, which is no
grammar at all.

**Where the state machine can lie.** Most of the model tests exist for
failures that leave a plausible-looking row. A failed load writes `error`, not
`loaded`. A failed *unload* writes `loaded`, not `error`, because as far as
anyone knows the weights are still resident and the memory budget has to keep
counting them. A crashed download writes `error` in a `finally`, since a row
stuck in `downloading` is one no later operation will touch and nothing sweeps
up. Deleting a model whose alias a routing policy names is refused: no foreign
key enforces that binding, and without the check inference starts answering
"no available model" with nothing in the registry to explain why.

The download job runs detached, in its own transaction, because the request's
session is closed the moment the response is sent. It does not survive a
restart, which is accepted rather than solved: a durable queue is a second
piece of infrastructure to run for one operation, and keeping progress in the
cache means an interrupted pull is visibly stuck rather than silently gone.
The set of strong task references in `infrastructure/jobs.py` is not
decoration — `asyncio` holds only weak ones, and a task nobody keeps can be
collected mid-await with nothing logged.

Two smaller things. SSE framing moved into one module, so the gateway and the
chat panel cannot drift into two envelope shapes; that drift is exactly what
made the chat panel display nothing the first time. And the runtime port now
declares `AsyncGenerator` rather than `AsyncIterator`, because every consumer
wraps it in `aclosing()` and only the former promises `aclose()` — the
promise the whole streaming contract rests on.

---

## 2026-07-24

### Admin authentication, end to end

Both admin entrances now resolve an identity, and a fresh deployment can get
from an empty database to a signed-in user on the public entrance. That path
is covered by an integration test which runs bootstrap, invitation, TOTP
enrolment, login and sign-out against a real Postgres, because none of the
unit tests would notice a composition root that wired the wrong adapter in.

Built: argon2id, pyotp, Fernet encryption for the TOTP secret, token issuing
and recovery codes, the audit adapter, sessions on the existing `CachePort`,
CSRF, the two identity resolvers, and the use cases behind them.

**Authentication was built before the CRUD, and the ordering paid off twice.**
Both times the shape of the existing schema rejected the first design rather
than accepting it quietly.

**The check constraint refused the obvious place to keep a pending TOTP
secret.** Enrolment spans two calls: one renders the QR, the other verifies a
code from the authenticator that scanned it, so the secret has to survive
between them. Writing it to the user row looked right, since
`can_use_public_entrance` already requires a password as well and a row with
only a secret authenticates nothing. But `users` carries
`(password_hash IS NULL) = (totp_secret IS NULL)`, added in the last review,
and it rejected the write. The constraint was right: a half-finished enrolment
is not an account. The candidate now waits in the cache for minutes, which is
better on its own terms. Abandoning a re-enrolment leaves the working
authenticator untouched, an unproved secret exists nowhere for 72 hours, and
the unauthenticated `begin` endpoint no longer writes to `users` at all.

**Creating an account and its invitation in one transaction violated a foreign
key.** The ORM models declare foreign key columns but no `relationship()`, so
SQLAlchemy's unit of work has no dependency graph to order a flush by, and
with `autoflush=False` — which production uses deliberately — the invitation
INSERT was emitted before the user it referenced. `PostgresUserRepository.save`
now flushes. This is the mirror of the defect found last time, where the tests
relied on an implicit flush that production does not do; here the production
code relied on an ordering nothing guarantees, and only a real database could
say so.

**A test-only hang that is worth recording.** The first end-to-end test opened
both entrances as concurrent `TestClient`s. It hung forever. `init_engine`
holds one engine per process and asyncpg connections belong to the event loop
that created them, so the second client's requests waited on futures from the
first client's loop. Production never meets this, because the entrances are
separate containers. The test opens them one after the other.

**And a latent ordering bug in the suite itself.** A unit test configures an
unreachable database to prove `/readyz` can fail, and cleared the `lru_cache`
on `get_settings` going in but not coming out. `alembic/env.py` overwrites
`sqlalchemy.url` with `get_settings().database_url`, so every integration test
that ran afterwards migrated against a dead host. It had never shown up
because the integration suite is skipped unless `TEST_DATABASE_URL` is set,
and the two had not been run together.

**Three decisions worth their reasoning.**

`PasswordHasherPort` is async, and the adapter runs argon2 in a bounded thread
pool. A hash occupies a core for tens of milliseconds, and login is
unauthenticated and behind no WAF, so a synchronous port would hand an
attacker a cheap way to stall every request in the process, including the ones
that would have rate limited them. anyio's default 40 threads at 64 MiB each
would then trade a CPU stall for an out-of-memory kill, hence the semaphore.

Audit rows are written in their own transaction. `session_scope` rolls back on
any exception, so an audit row sharing the request's session disappears
exactly when the request failed, and failures are what an audit log is for.
The cost is the mirror case, an audited action that later rolls back, which is
what `outcome` is for.

The entrances choose their identity resolver by dependency override, and the
placeholder raises. A branch on `settings.auth_mode` would have been a string
comparison deciding a trust model, which is the thing section 5.1 says the
isolation must not rest on. An application that installs neither resolver now
fails on its first authenticated request rather than defaulting to anything.

Two things changed outside the plan. `users` gained a `created_at` column,
because the frontend user schema already displayed one and no column existed.
And the invitation QR endpoint takes the token on its URL: the recipient is
not signed in, so there is no session to identify the enrolment from, and an
`<img>` cannot carry a request body.

Still absent, and the reason the frontend is not yet usable end to end: models,
routing policies, API keys, jobs, dashboard, `/admin/chat`, and the rest of
`/users`.

### Theme and progress tracking

Deep blue theme, a busy indicator, and this file.

The palette is computed rather than chosen by eye: `#1e40af` measures 8.72:1
against white, which clears AAA for body text, and dark mode moves up the ramp
to `#60a5fa` at 7.79:1 against the dark background rather than reusing a value
that would be unreadable there. Charts use a sequential ramp, because the
dashboard shows magnitude over time and a categorical palette would imply
categories that do not exist.

Two decorative elements adapted from Uiverse.io, credited in
[`ATTRIBUTIONS.md`](../ATTRIBUTIONS.md). Only two, and only decorative: that
collection is thousands of pieces by as many authors with no shared design
language and, being showcases, generally no focus or disabled states. Useful
for a spinner, wrong for anything a user operates.

**No logo.** A constructed wordmark and an N-as-routing-graph icon were drawn
and then discarded; the identity will come from elsewhere. There is no icon
asset in the repository, so the browser tab falls back to the framework
default until one is supplied.

### Everything the adversarial review found, fixed

Five independent reviews were run against the codebase, each attacking a
different surface. Their findings were verified before acting, which mattered:
the loudest one was wrong.

**The claim that did not survive verification.** A review argued that streaming
requests never commit their usage record, because FastAPI closes a
yield-dependency before a streaming response is produced. The reasoning was
sound and the conclusion was false for the installed version. An empirical test
showed both paths persisting. A second review found why: FastAPI 0.139 keeps
the dependency scope open until the response is sent, but the declared floor
was `>=0.115`, and versions in between do not. So the real defect was a
dependency range, not a design fault, and the fix was a pin plus the
regression test that had been missing.

**Live security holes, since the gateway is the only exposed surface.**
Scopes were computed and then never consulted, so any valid key could consume
the hardware regardless of what it was issued for. The per-key quota was dead
in two independent ways. `rate_limit_rpm` was stored end to end and enforced
nowhere. `TAILNET_IP` had no required-variable guard, so an unset value made
Compose bind the gateway to every interface, which was verified before and
after.

**The one worth remembering.** The quota read `tokens_used_today` off the key
repository through a `getattr` fallback that returned zero when the method was
missing. The method lives on a different class. The fallback had been written
to make the check stubbable in tests, and it was precisely what hid the
miswiring: the only object with that method was the test double, so the tests
passed while production never checked a quota at all. A defensive default
around a wiring mistake is worse than the crash it prevents.

**Frontend.** The chat could never display a reply: the frame schema described
a flat shape while the backend sends the OpenAI envelope, and zod strips
unknown keys rather than rejecting them, so every real frame parsed
successfully into an empty object. The login page was an open redirect via
`/\evil.example`, which the URL parser normalises to a second slash. One-time
secrets could be destroyed with the Escape key. `Me` carried no `id`, so two
callers substituted `login` and one of them left an admin able to delete
themselves.

**Persistence.** Single use was not single use: the atomic guard was correct
and its rowcount was discarded, so two requests reaching the same invitation
both believed they had claimed it. TOTP replay prevention compared a value
read earlier and wrote it back, which two concurrent requests both pass.
Invariants that existed only as Python properties are now check constraints.

**Documentation.** Several controls were described in the present tense and did
not exist. The worst was in `db.py`, whose docstring asserted that each service
connects with its own least-privilege account and that "the grants do the
enforcing", while Compose gives every service one account that owns the schema.
That is the same mistake `security.md` had already warned about for tenant
isolation: a claimed boundary stops people looking for the risk.

**Two defects were found by the new tests rather than by review.** Splitting a
use case into two generators reintroduced a missing `aclosing` one layer up,
caught immediately by the disconnect test. And aligning the test sessions with
production `autoflush=False` produced foreign key violations, because the tests
had been relying on an implicit flush that production does not do.

### Guardrails that were configured but never read

Four settings existed in `config.py`, in `.env.example` and in the
documentation, and were read by nothing.

`/readyz` returned hardcoded booleans, so it could never produce a 503, and its
test asserted only that the status was one of 200 or 503 and therefore passed
vacuously. Anything gating a rollout on readiness was gating on a constant. It
now probes the database, cache and runtime concurrently, each bounded by a
timeout, because a probe that hangs is worse than one that fails: the
orchestrator waits instead of acting.

The country filter did not exist at all. `geoip2` was a dependency,
`allowed_countries` and `geoip_db_path` were read by nothing, and
`CountryNotAllowedError` was defined and never raised, which is worse than
absence because a defined error implies a control. It now refuses to start in
production when its database file is missing, rather than silently serving
every country.

`max_context_length` was likewise inert, so a prompt of any size was accepted.
And `/docs` was gated on `not is_production`, but `ENV` defaults to development
and `.env.example` ships it, so a deployment that filled in its secrets and
left the top of the file alone was publishing its full internal schema.
Exposure is now an explicit opt-in, so forgetting fails closed.

### Phase 1 backend, end to end

Postgres repositories and the first migration, the Ollama adapter, and the
chat path wired from socket to SSE frames.

The runtime is stubbed in the end-to-end tests and nowhere else. Inference
needs a GPU and can only be verified on the Mac Studio; everything between the
socket and the port boundary is real, including the routing policy read from
the database.

Three defects found while building: `.env.example` shipped a `DATABASE_URL`
whose password did not match `POSTGRES_PASSWORD`, so a fresh checkout could not
connect; `alembic/script.py.mako` was missing, so revision generation failed
outright; and `key_id` was an independent random value that appeared nowhere in
the token, leaving verification no way to find the row short of scanning every
key.

### Scaffold

Backend hexagonal skeleton, Next.js management UI, Compose topology, AGPL-3.0.

The hardware constraint that shaped the deployment: **model runtimes cannot run
in Docker on macOS**, because containers there have no GPU access. A
containerised Ollama would be CPU-only and MLX would not run at all, which
defeats the point of the machine. Runtimes are native under launchd; containers
reach them through `host.docker.internal`.

Three image-build defects that only appeared by actually running
`docker compose build`, all of which `docker compose config` validated happily:
four services declaring `build:` while sharing one tag raced to write it,
`package.json` had no `packageManager` for corepack to activate, and neither
build context had a `.dockerignore`, so the host's `node_modules` and a Windows
x86 `.venv` were being copied into Linux images.

### Licence: AGPL-3.0

Chosen to match the sibling project, Smart-MultiAgent-Platform, so code can
move between them without a licensing question, and held by the research
centre rather than an individual so that people moving on does not create a
reattribution problem.

Section 13 is why this is not merely administrative here. Unlike the GPL, the
AGPL treats network interaction as distribution, and this platform exposes both
a public inference API and a public management UI. Anyone reaching those
endpoints is entitled to the source of the running version, which makes it an
operational obligation: keep the deployed revision published and identifiable,
not just ship a LICENSE file. Recorded in `deployment.md` section 8.1 for that
reason.

### The public entrance, and the risks accepted with it

The original plan was Cloudflare Tunnel. It was dropped after checking two
things rather than assuming them.

`rcsl.online` is served by Gandi nameservers and the domain is actively
receiving mail through Gandi, so moving nameservers touches mail delivery on a
shared domain maintained by someone else. And Cloudflare's free tiers fix the
origin response timeout at 100 seconds, which streaming survives but a long
non-streaming completion does not.

So public traffic goes through the existing openresty proxy at NTNU instead. A
wildcard DNS record already points every subdomain there, so no DNS change is
needed; what is needed is that the proxy host joins the tailnet and forwards
two hostnames. Three consequences were accepted deliberately and are recorded
in `security.md` section 15 with the conditions that should trigger revisiting
them: inference traffic passes through a third party in plaintext, there is no
edge WAF or DDoS protection, and the country filter is bypassable by anyone
with a VPS in the right country.

The second of those is why the resource guardrails matter more here than they
would behind a CDN. They are not one layer of several; they are the only one.

### Architecture documents

Six documents, and the decisions behind them.

The one that shaped everything else: the gateway and the admin API must be
separate containers, because the isolation has to come from socket binding
rather than from a path rule in a reverse proxy that one typo could undo. That
in turn made the two admin entrances separate ASGI applications, since the
tailnet entrance trusts an identity header outright and sharing a socket with
the public entrance would let a forged header grant administrator access.

Authentication moved from OIDC to invitation-only local accounts with mandatory
TOTP, on the reasoning that the platform was already invitation-only in effect
(the `users` table gates access, not the identity provider), so the real choice
was who verifies the password. The trade is explicit: no external dependency
and no account an administrator did not create, in exchange for owning password
storage, reset, lockout and second-factor handling permanently. Mandatory TOTP
is what makes that trade acceptable.

A hardware constraint found while writing these, not while coding: model
runtimes cannot run in Docker on macOS, because containers there have no GPU
access. It contradicted the stated goal of keeping the host clean and was
non-negotiable, so the documents changed rather than the plan.

---

## Where things stand

Phase 1's functionality is complete. Inference, authentication on both admin
entrances, and the management API are all built and tested, and every screen
in the frontend now reaches a real backend. The remaining Phase 1 items are
operational rather than functional.

The Mac Studio is now the development machine as well as the deployment target,
and the backend suite runs on it: 359 tests on Python 3.12 against a real
Postgres 17. What that does *not* yet cover is anything requiring the stack to
be up — GPU inference, the tailnet entrance, and nginx behaviour remain
unverified by construction, and the runbook's first deploy has not been done.

One thing still exists as an API with no dedicated UI: the download progress
endpoint, which the models table polls but no page surfaces on its own. The
routing policy editor now exists, so a policy is no longer curl-only.

## What comes next

The three Phase 1 finishing items are now done, each recorded in a dated entry
above: a **frontend test runner** (Vitest over the units where a defect is a
security defect), the **routing policy editor**, and the **database account
split with secrets on file mounts**. Phase 1's functional and control-plane work
is complete; what is left is verification that can only happen on the target
hardware.

The frontend test runner covers logic units only; component and browser (E2E,
Playwright) coverage of the sign-in and enrolment screens is still the deferred
increment, recorded in `ROADMAP.md` Phase 3. And the database split, the secret
mounts, GPU inference, the tailnet entrance and nginx are all verified only
structurally so far, which is what the Mac Studio deploy below is for.

### Then: deploy to the Mac Studio for the first time

This is a milestone in its own right because several things can only be tested
there, and because it needs another person. The step-by-step is in
[runbooks/first-deploy.md](./runbooks/first-deploy.md); the essentials:

- Install Ollama natively under launchd as a dedicated service account, bound
  to `127.0.0.1`.
- Ask the NTNU proxy administrator for four things, listed in `ROADMAP.md`:
  join the tailnet under `tag:ntnu-proxy`, add two nginx server blocks, issue
  Let's Encrypt certificates, and confirm no request-body logging.
- Populate `./secrets` from `secrets/README.md`: three distinct database URLs,
  the postgres password matching the owner URL, and real values for the rest.
- Confirm the account split holds against the live database, which nothing has
  exercised yet: `migrate` creates the two roles and their grants, each service
  connects as its own account, and the gateway's account is refused an INSERT
  into `api_keys`.
- Work through the pre-launch checklist in `security.md` section 14. Several
  items say to test rather than assume, and mean it: the forged
  `Tailscale-User-Login` case, the forged `X-Forwarded-For` case, and
  `AUTH_MODE=dev` refusing to boot under `ENV=production`.

### Phase 2 and beyond

Detail in `ROADMAP.md`. The parts that will need real design work rather than
implementation:

- **A second runtime adapter** (vLLM or MLX). Worth doing early even if unused,
  because it is the only real test of whether the hexagonal layering delivered
  what it was chosen for. If adding one requires touching a use case, the
  abstraction failed.
- **Multi-tenancy.** Currently single tenant, stated as such. The Phase 1
  schema was written not to preclude it, but adding `tenant_id` touches every
  repository and the filter has to be injected inside the adapter so a caller
  cannot forget it.
- **Prometheus and Grafana** are now built on the emission side (see the
  2026-07-25 entry). What remains is the ingestion half: a live free-memory
  figure feeding the memory budget, which needs the Mac Studio to produce a real
  one.
- **A second compute node**, which is the point of the node abstraction and
  will be the first time routing has more than one place to send anything.

### Open decisions

- **Whether to move `rcsl.online` to Cloudflare**, or register a separate cheap
  domain for the data plane. Either removes the accepted risk in `security.md`
  section 15.1, where inference traffic passes through a third-party machine in
  plaintext. Deferred, not settled.
- **Where the identity comes from.** No logo; the drawn one was rejected.
- **Whether the admin API should be reachable publicly at all.** It is designed
  for it and the entrance exists, but nothing depends on it yet, and closing it
  would remove an entire attack surface. Worth asking again once the tailnet
  entrance is in use and it is clear who actually cannot install Tailscale.

### Standing risks to revisit

`security.md` section 15 records four accepted risks with the conditions that
should trigger reconsidering them. The one most likely to change is 15.1: if
the platform starts handling personal or IRB-regulated data, plaintext
inference traffic through a third-party proxy stops being acceptable and the
Cloudflare question above becomes urgent rather than optional.
