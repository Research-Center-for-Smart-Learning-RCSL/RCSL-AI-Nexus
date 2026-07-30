# RCSL AI Nexus: Roadmap

Mirrors the layering in [ARCHITECTURE.md](./ARCHITECTURE.md), breaking the three original phases into milestones this repository can actually deliver.

## Phase 0: Base Infrastructure (on the Mac Studio, mostly outside this repository)

- SSH and Tailscale
- Docker Desktop or an equivalent
- Unified directory layout: `/models`, `/data`, `/logs`, `/config`
- **Model runtimes installed natively on macOS**, not in Docker. Ollama under launchd, `OLLAMA_HOST=127.0.0.1`, running as a dedicated service account. Docker on macOS cannot reach the GPU, so a containerised runtime would be CPU-only and MLX would not run at all. See [ARCHITECTURE.md](./ARCHITECTURE.md) §0.1
- Everything else managed by Docker Compose

## Phase 1: MVP, a Minimal Management Platform That Works End to End

Goal: one capability (`chat`) can be configured through the admin UI and actually served by the gateway. Architecture detail in [backend.md](./architecture/backend.md), [frontend.md](./architecture/frontend.md), [security.md](./architecture/security.md), and [deployment.md](./architecture/deployment.md).

### Where Phase 1 actually stands

The inference half is done; the management half is not. `security.md` §13.0
carries the checked control-by-control state.

| Area | State |
|---|---|
| `/v1/chat/completions`, streaming and not | Complete, tested end to end against a real Postgres. Carries two non-OpenAI additions for thinking models: a `reasoning_content` delta key and a `think` request field ([backend.md](./architecture/backend.md) §6) |
| Routing, registry, keys, usage: persistence | Complete, migrations tested |
| Ollama adapter, reference validation | Complete |
| Gateway security: scopes, quota, rate limit, CIDR, geo, guardrails | Complete |
| Local accounts, TOTP, sessions, CSRF, bootstrap | Complete, tested from a fresh deployment to a signed-in user |
| Both admin entrances: identity resolution, `/me` | Complete. Each installs its own resolver; neither can default to the other's |
| Invitation and password reset flows, both ends | Complete |
| Audit logging | Adapter written, and every administrative action records one |
| Admin API: models, downloads, routing policies, API keys, users, dashboard, `/admin/chat` | Complete, exercised end to end against a real Postgres |
| Node management | Read only. The single node is named in configuration; a write endpoint ships with the SSRF guard ([security.md](./architecture/security.md) §7.2) |
| Database account split, Docker secrets in Compose | Complete. Three least-privilege Postgres accounts provisioned by `migrate`; all credentials mounted as Docker file secrets. Proven against a live Postgres 17 (`tests/integration/test_db_role_grants.py`, which was silently asserting nothing between the multi-tenancy migration and 2026-07-26 — see [PROGRESS.md](./PROGRESS.md) 2026-07-26) and by a full `ENV=production` Compose smoke test on the dev machine: `migrate` provisions the roles, each service connects as its own account, and the gateway is refused an `api_keys` write. Only the Mac-specific bits (GeoLite2, GPU, `tailscale serve`, nginx) remain unexercised |
| Frontend | Every screen now reaches a real backend. Vitest covers the security-critical logic units; no E2E runner yet |
| Adversarial review of the admin API | Five independent reviews run; 28 findings verified and fixed across four commits, residuals recorded in [security.md](./architecture/security.md) §13.0 and §15.5 |

### Backend: hexagonal skeleton

- [x] Five layers: `domain` / `application` / `adapters` / `interfaces` / `infrastructure`
- [x] `domain/entities`: `Model`, `Node`, `Capability`, `RoutingPolicy`, `ApiKey`, `User`, `Actor`, `UsageRecord`
- [x] `domain/services`: `RoutingService` (structured requirement matching, **never expression evaluation**), `MemoryBudgetService`, `ApiKeyService`, `TokenService`, `LoginThrottle`
- [x] `domain/ports`: runtime, repositories (model, node, policy, api key, user, usage), authorization, audit, cache, job progress
- [x] `domain/exceptions.py`: `DomainError` hierarchy with `code` and `public_message`
- [x] `adapters/runtime/ollama_adapter.py` plus `validation.py` for model reference parsing
- [x] `adapters/persistence/`: Postgres implementations, ORM models kept separate from entities
- [x] `adapters/authz`, `adapters/audit`, `adapters/cache`, `adapters/crypto`, `adapters/session`
- [x] `application/use_cases`: `RouteChatRequest`, `AuthenticateLocal`, `AcceptInvitation`, `IssueInvitation`, `ManageOwnAccount`, `BootstrapFirstAdmin`, `ManageModels`, `DownloadModel`, `ManageApiKeys`, `ManageUsers`, `ManageRoutingPolicies`, `ListCapabilities`, `ReadDashboard`
- [x] `interfaces/http/errors.py`: single exception handler, OpenAI envelope on the gateway, plain shape on admin
- [x] Routers: `chat` (`/v1/chat/completions` and `/v1/models`), `admin_chat`, `models` (download progress included, rather than a separate `jobs` router as sketched), `routing_policies`, `api_keys`, `gateway_info`, `users`, `auth`, `me`, `invitations`, `tenants`, `dashboard`, `usage`, `logs`, `health`, `metrics`
- [x] `interfaces/http/sse.py`: one framing implementation, so the gateway and the chat panel cannot drift into two envelope shapes
- [x] **Three ASGI entry points**: `main_gateway`, `main_admin_tailnet`, `main_admin_public`, each installing its own identity resolver
- [x] Streaming contract implemented as specified: concurrency slot spans the generator, `aclosing()` at every consumer, cancellation propagates to the adapter, usage recorded in `finally`
- [x] `interfaces/http/middleware/identity.py`: per-entrance identity resolution, installed by dependency override so an entrance that chooses neither fails closed
- [x] `infrastructure/di.py` composition root, Ollama only
- [x] `infrastructure/config.py` with `secrets_dir`, and a startup assertion that `AUTH_MODE=dev` cannot run under `ENV=production`
- [x] Alembic migrations: `nodes`, `models`, `routing_policies`, `api_keys`, `users`, `invitations`, `recovery_codes`, `usage_records`, `audit_log`
- [x] `tests/unit`: routing selection, streaming lifecycle (slot release on disconnect), dev-mode fail-fast, header stripping, login rules, session invalidation, TOTP replay, password policy, entrance wiring
- [x] `tests/integration`: repository invariants, and a fresh deployment through bootstrap, invitation, enrolment and login

### Frontend

- [x] Next.js project plus `shadcn/ui init`
- [x] `src/middleware.ts` proxies `/admin/*` so it is same-origin. Was a `next.config.js` rewrite until 2026-07-26, which `output: 'standalone'` resolves at build time, baking a localhost fallback into the deployed image
- [x] `components/ui`: Button, Input, Table, Dialog, Badge, Tabs, Toast
- [x] `features/models`: node selection, now that `GET /nodes` exists
- [ ] `lib/generated`: `openapi-typescript` against the **admin** port (the gateway serves no schema)
- [x] `features/routing-policies`: table plus a candidate editor (per-capability, `useFieldArray` over candidates, structured requirement checkboxes), so a policy is no longer edited with curl
- [x] `lib/session.tsx`: consumes `/admin/me`, exposes `auth_mode` through context
- [x] `lib/api-client.ts`: `credentials: 'include'`, automatic CSRF header on mutations, 401 handling that branches on `auth_mode`
- [x] `components/composed`: `DataTable`, `StatCard`, `FormField`, `ConfirmDialog`, `StatusBadge`, `StreamMessage`, `EmptyState`, `ErrorState`
- [x] `features/models`: table, form dialog, download progress via `useDownloadJob` (the hook and `DownloadProgress` were built but never referenced from the table, so a registered model could not be downloaded at all until 2026-07-26 — see [PROGRESS.md](./PROGRESS.md))
- [x] `features/chat`: SSE consumption with abort on unmount, terminal error frames surfaced
- [x] `features/users`: list, invite (copyable single-use link), role change
- [x] `features/auth`: two-step login, invitation acceptance with TOTP QR and recovery codes, password change
- [x] `features/api-keys`: issue, edit, revoke, with actions gated on the scopes the backend actually grants so a member manages their own keys. The edit dialog closed a gap where `PATCH /api-keys/{key_id}`, its client function and its hook all existed with no component reaching any of them ([PROGRESS.md](./PROGRESS.md) 2026-07-28)
- [x] `features/gateway` and the `/api-docs` page: the base URL, the capability convention, paste-ready snippets shown at issue, and the error code table. This is the "public API documentation written separately" that [security.md](./architecture/security.md) §4.4 promises in exchange for disabling `/openapi.json` and `/docs` on the gateway — a trade that was only a trade once the documentation existed
- [x] `features/dashboard`: registry counts plus 24-hour totals; the charts read the real `/admin/usage` series
- [x] Markdown rendering sanitised, raw HTML disabled
- [x] Vitest unit coverage of the logic where a defect is a security defect: `safe-redirect` (open redirect), the chat SSE schema and reader (envelope parsing, error and truncation frames), `api-client` (CSRF header, 401 handling, no `Authorization`), and the password schema
- [ ] Component and E2E coverage (Playwright, listed in Phase 3): the sign-in and enrolment screens are not yet driven through a browser

### Infrastructure

- [x] `docker-compose.yml`: `gateway`, `admin-tailnet`, `admin-public`, `frontend-tailnet`, `frontend-public`, `postgres`, `redis`, `migrate`
- [x] Networks `app` and `data` (`data` is `internal: true`); no service publishes on `0.0.0.0`
- [x] `migrate` as a one-shot service; all applications gate on `service_completed_successfully`
- [x] `tailscale serve` for the tailnet entrance. Configured and serving:
      `https://rcslmac1demac-studio.tail68e30b.ts.net` proxies to `127.0.0.1:3000`, port 443
      listening on the tailnet address, 200 over it. One caveat found on 2026-07-26 and not
      yet chased: the MagicDNS name does not resolve **on the host itself** even though
      `CorpDNS` is true, so the check above had to pin the address with `--resolve`. That
      does not affect the entrance's users, who reach it from other devices — but it means
      the entrance has never been confirmed end to end from a device that is not this one,
      and that is the confirmation that counts
- [x] Health endpoints wired into Compose health checks

### External coordination (can proceed in parallel)

- [ ] Proxy host joins the tailnet, tagged `tag:ntnu-proxy`
- [ ] Two nginx server blocks, plus the HTTP-to-HTTPS redirect block
- [ ] Let's Encrypt certificates for both hostnames
- [ ] Confirm no request body logging and no Lua interception
- [ ] Confirm `proxy_buffering off` and `proxy_read_timeout`
- [ ] Request explicit A records rather than relying on wildcard synthesis

### Security: required before anything is exposed publicly

Full list in [security.md](./architecture/security.md) §13, checklist in §14.

[security.md](./architecture/security.md) §15.5 (the gateway forging an administrator identity to the tailnet entrance over a shared Docker network) is now closed: the data plane and control plane are on separate networks and share nothing. The §6 per-service database credential split is now implemented too, so a compromised gateway can neither reach the admin socket nor write `api_keys` or `users` directly. Both are verified only structurally so far (`docker compose config`, unit tests); the live grants are exercised at the first Mac Studio deploy.

- [x] Public admin entrance strips every `Tailscale-*` header unconditionally
- [x] Tailscale ACL including `tag:ntnu-proxy`, so members cannot bypass the proxy. Applied to the real tailnet on 2026-07-26, not merely written: the server carries `tag:ai-server`, and the no-bypass property is pinned by the `tests` block in [security.md](./architecture/security.md) §3.4, which Tailscale runs on every policy save. `tag:ntnu-proxy` itself waits for the proxy host to join
- [x] Trusted-proxy client address resolution using the shared secret header, not peer IP
- [x] Country filter on **both** the gateway and the public admin entrance
- [x] Per-key CIDR allowlists
- [x] API keys: HMAC with pepper, random `key_id` lookup, scopes, mandatory expiry, immediate revocation. The capability list is enforced as of 2026-07-28 and was not before: `RouteChatRequest` checked `chat:use` and then routed on whatever the request named, so a key issued for `chat` reached every capability the deployment served, while a key issued for `code` alone mapped to no scope and was refused everything. Which capability now travels on `Actor.allowed_capabilities` and is checked where the capability is read; the scope table stays hardcoded so no stored list can promote a key into the control plane ([PROGRESS.md](./PROGRESS.md) 2026-07-28)
- [x] Local accounts: argon2id, zxcvbn strength check, no user enumeration, escalating rate limits rather than hard lockout
- [x] TOTP mandatory at enrolment, with counter replay prevention and single-use recovery codes
- [x] Invitation and reset links: single use, hashed at rest, expiring; the platform never transmits a password
- [x] Server-side sessions in Redis, `__Host-` cookies, id rotation on login, invalidation on password change, CSRF double-submit
- [x] First-admin bootstrap, tailnet entrance only, inert once users exist
- [x] Separate database accounts; gateway cannot write `api_keys` or `users` (`infrastructure/db_roles.py`, provisioned by `migrate`)
- [x] Default credentials replaced: Redis, Postgres, Grafana and now Qdrant take real values from Docker file secrets (Grafana with anonymous access and self-registration disabled). Qdrant ships with **no authentication at all**, so its key is required to be a real value in production unconditionally, unlike the metrics token which is only required when metrics are enabled: there is no deployment shape in which an unauthenticated knowledge base is intended. MinIO never arrived; document storage is a volume ([ARCHITECTURE.md](./ARCHITECTURE.md) §4)
- [x] Model reference validation; no shell string construction anywhere
- [ ] Host runtime hardening: service account, `127.0.0.1` binding, directory ownership
- [x] **Resource guardrails: concurrency cap, `max_tokens`, context bound, per-read timeout, wall-clock generation deadline, cancel on disconnect.** With no edge protection these are the only defence. All enforced in `RouteChatRequest`; the concurrency slot spans the whole generator and disconnect cancellation propagates to the adapter (backend.md §6). The wall-clock deadline is the last piece: a slow-but-steady stream that stays under the per-read timeout yet never reaches the token cap would otherwise hold a slot for hours on unified memory near swap. Verified by unit tests against an injected clock, and since 2026-07-27 against real GPU behaviour on the Mac Studio, which resized two of them: the token ceiling counts a thinking model's reasoning, and the wall-clock deadline has to stay below the frontend's proxy timeout or the cut arrives with no reason attached (see [PROGRESS.md](./PROGRESS.md) 2026-07-27)
- [x] `AuditPort` adapter, and auditing for bootstrap, invitations, resets, credential changes, key issuance and revocation, model registration, download and load, role changes and account removal
- [x] gitleaks pre-commit hook

## Phase 2: Full Management Functionality

- [x] Second runtime adapter (MLX), proving swappability without touching use cases or interfaces. Done: one adapter file plus three wiring points (`build_runtimes`, one setting, one Compose mount); `application/use_cases` and `interfaces` untouched, domain untouched. The layering held. What it surfaced is recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25: MLX has no download-with-progress endpoint (so `pull` downloads via `huggingface_hub` into a host-shared cache) and no unload (so `unload` refuses rather than desyncing the memory budget). Real MLX inference and a real download still wait for the Mac Studio, the same boundary Ollama inference has. vLLM stays deferred until there is NVIDIA/Linux hardware it runs on
- [x] Routing policy editor UI, including fallback configuration (the ordered candidate list with per-candidate priority and requirements is the fallback mechanism; shipped in Phase 1)
- [x] Node management UI, `NodeHealthPort`, heartbeats, and the SSRF guard shipping alongside the first node write endpoint. Done: `adapters/http/egress_guard.py` validates every node address against the tailnet range at write time (the rule in [security.md](./architecture/security.md) §7.2 that a write path may exist only with the guard); `NodeHealthPort` plus a heartbeat in the admin app replace the always-`online` assumption so a `node_status: [online]` requirement reflects reality; `ManageNodes` + `routers/nodes.py` carry register/edit/delete/check with attached-model and duplicate-name guards and audit; the frontend `features/nodes` screen shows live status. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25. Real runtime probing waits for the Mac Studio
- [x] Multi-tenancy: `Tenant` entity, `tenant_id` columns, repository-enforced query filters. Done as the foundation plus minimal management: `users`, `api_keys`, `usage_records` and `audit_log` carry `tenant_id` (models/nodes/routing stay platform-global), the tenant-scoped repositories filter reads and stamp writes from the actor's tenant (injected in the di builder, never taken from the caller, per [security.md](./architecture/security.md) §7.3), and identity/bootstrap use an explicit unscoped variant. `ManageTenants` creates tenants (minting a first-admin invitation into the new tenant) and lists them. Isolation is pinned by an integration test against real Postgres. No platform-super-admin split yet; recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25
- [x] Logs UI. Done: a read-only, admin-only audit view (`logs:read`) over the append-only `audit_log`, server-paged with action and outcome filters. A tenant-scoped read repository (`PostgresAuditLogRepository`) plus `ReadAuditLog` on the backend, `features/logs` on the frontend. Tenant isolation of the read is pinned against real Postgres. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25
- [x] Usage analytics with charts. Done, and the chart-library question is settled: no library. The data is simple magnitude-over-time, so the charts are inline SVG (`components/composed/metric-chart.tsx`, geometry in `chart-geometry.ts`), theme-aware through the `--chart-1..5` ramp, which sidesteps the Tremor/Recharts supply-chain and React 19 concerns entirely ([frontend.md](./architecture/frontend.md) §7). Backend: a `date_trunc` aggregation (`bucketed_usage`) and `ReadUsageAnalytics` behind `usage:read_all`, with `GET /admin/usage`; frontend: `features/usage` plus real series wired into the dashboard's two charts. The bucketing is verified against real Postgres. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25
- [x] Prometheus and Grafana, the emission side. Done: `/metrics` on all three apps behind a bearer-token guard (`adapters/metrics/prometheus.py`, `interfaces/http/middleware/metrics.py`, `interfaces/http/routers/metrics.py`); HTTP series via a streaming-safe pure-ASGI middleware, inference series derived from the existing `UsageRecord` through a `MeteredUsageRepository` (so the streaming use case is untouched), and a scrape-time concurrency-slot gauge. Prometheus is on internal-only networks and publishes no port (`docker-compose.yml`, `prometheus/`, `grafana/`); Grafana is on those plus a dedicated non-internal `viz-ingress`, because Docker cannot publish a host port into an internal network — its `127.0.0.1:3002` had in fact never bound once until this was found on 2026-07-26 ([security.md](./architecture/security.md) §6). Grafana's password is a file secret with anonymous access and self-registration off. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25. **Live metrics replacing the static memory budget is deliberately not done**: the `MetricsPort` figure the budget reads is a real free-memory number only on the Mac Studio, so the budget stays static and authoritative until then ([security.md](./architecture/security.md) §4.3)
- [x] **Reconcile the registry's `loaded` state against what is actually resident.** Done 2026-07-30 as an intent/observation split rather than a rewrite: the heartbeat's new residency half asks each runtime what it holds (Ollama via `/api/ps` and `/api/tags`; MLX answers "cannot say", the same refusal its `unload` makes) and writes `observed_state`/`observed_memory_gb`/`observed_at` beside the intent it may contradict. Routing's `model_state` requirement follows the observation when one exists, the models screen shows the divergence, and `state` itself is never auto-corrected — intent stays the operator's. An unreachable runtime clears the observation rather than asserting absence, so readers fall back to intent, the pre-observation behaviour. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-30
- [~] `MetricsPort` ingestion. The half that mattered is done via the same residency read-back: the memory budget now counts the runtime's own resident figure (KV cache included — 38 GB observed against 32 declared for `glm-4.7-flash`) instead of the hand-typed profile, and counts models the runtime holds that intent never claimed. What remains is a genuine host free-memory figure covering the OS and containers, which nothing a container can reach produces; the port stays unimplemented until a host-side exporter is warranted
- [x] Management assistant embedded in the admin UI. Done as an **advisory** drawer, mounted by the app shell so one conversation follows the operator across screens: it answers questions about this deployment's settings and, on the two API key forms, offers values the operator applies and saves themselves. No tool call, no write path, no new authorization edge — every write still goes through the dialog that always performed it, with its existing scope check and audit record. Backend: `AssistOperator` assembling the system prompt from live domain values, `POST /admin/assistant` on the admin entrances only, and one optional trailer frame added to the shared SSE framing. Frontend: `features/assistant` plus a typed page-context registry that no dialog can push a key's plaintext through. Boundary, controls and residual risk in [security.md](./architecture/security.md) §7.5; recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-29.
      **Deployed and verified on the Mac Studio the same day.** The two prerequisites were operator work rather than code — `assist` needs a routing policy pointing at a fast, non-deliberating model, and that model has to be resident — and both were already satisfied: `qwen2.5:7b` was registered and loaded, and Ollama reports it with no `thinking` capability at all. The policy could only be written *after* the deploy, since the previous image had no `assist` in its capability set, so the two cannot be ordered the other way. Confirmed live: an `assist` policy exists and `GET /admin/gateway` still answers `["chat"]`, which is the property the two-set split exists for; the drawer answers in 6.6 seconds where `chat` had spent 10m53s answering nothing
- [x] Review of the assistant commit, and its fixes. Eight findings, two of them behavioural: the proposal holdback was released after the terminal SSE frame, so every answer lost its last nine characters to any client that stops reading there (the same mistake recorded against `RouteChatRequest` on 2026-07-27), and the page-context registry was a slot rather than a stack, so closing a dialog took the assistant's context away from the screen still in front of the operator. One reported finding was wrong and had been repeated as fact before being checked; the change written for it was reverted. Each fix was then verified by putting its defect back, which caught a test that passed either way. See [PROGRESS.md](./PROGRESS.md) 2026-07-29
- [x] Split issuable from routable capabilities (`ISSUABLE_CAPABILITIES` / `ROUTABLE_CAPABILITIES`). Prompted by `assist` but a gap in its own right; §7.5.1 covers the two readers that needed it applied by hand, including the one that made a direct `api_keys` write reach a capability the issuing path refuses
- [x] Knowledge base with Qdrant, isolated document parsing, upload validation, and retrieval wired into the chat. Done across four commits, recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-30. The parts that were decisions rather than implementation: **document parsing runs in its own container** whose isolation is subtraction (no settings, so no credential to read; no volumes, so nothing to write; one internal network, so no route to the internet, Postgres, Redis or Qdrant; a read-only root and a memory limit), with a test that parses the package with `ast` and fails if it ever imports from the application; **documents live on a volume rather than MinIO** ([ARCHITECTURE.md](./ARCHITECTURE.md) §4); **embeddings go through the existing routing policy** on the `embedding` capability rather than a setting of their own, so an embedding model is registered, budgeted and routed like any other and MLX refuses to embed rather than returning a plausible wrong vector; **the vector store's tenant boundary is enforced twice and the first layer fails closed**, since each tenant gets its own Qdrant collection and a lost tenant then names a collection that does not exist rather than reading everyone's passages; and **Qdrant's read-only key goes to the gateway**, so retrieving a passage cannot become writing one, the same §6 split its database account has. Verified end to end on the Mac Studio on 2026-07-30 — upload, isolated parse, embedding through the policy, Qdrant, semantic search, and a grounded chat answering from the document with its citation header ([PROGRESS.md](./PROGRESS.md) 2026-07-30). Retrieval *quality* at scale remains open: one small document proves the path, not the ranking
- [ ] Knowledge base follow-ups: re-index without re-upload (the extracted text is already kept for it), and a document preview
- [ ] Prompt template management
- [ ] Logging boundaries and the expiring debug switch on both keys and users
- [ ] Full audit coverage across every event in [security.md](./architecture/security.md) §12
- [ ] Authorization checks covering every use case
- [ ] Encrypted backups and a rehearsed restore
- [ ] Storybook stories for `components/composed`

## Phase 3: Operations and Multi-Node

- [ ] Second compute node registered and serving
- [~] Automatic restart and health alerting. Alerting is done: `launchd/check-platform-health.sh` and its LaunchDaemon check seven properties every five minutes — expected services running, requested-versus-actual host bindings, all six entrances over their published ports, Ollama on loopback and not on the tailnet address — and mail on a change of state, with a daily heartbeat so that silence is also a signal ([deployment.md](./architecture/deployment.md) §9, runbook §7, the sending credential as an accepted risk in [security.md](./architecture/security.md) §15.7). Both halves of the monitor are now proven by a boot rather than by hand: the daemon survived the 18:08 reboot and kept its five-minute interval, and it sent a heartbeat itself under launchd at 18:53:20 (every earlier mail had come from a hand run). It has also now been through a real failure rather than a drill — `failing` at 19:14:59 on the 19:10 boot that came back with no containers, `recovered` at 19:30:03 — which is the one part of the chain that has been exercised end to end by an actual fault. One blind spot in it was found and closed the same evening: it asked `docker compose ps` without `--status running`, which excludes only *stopped* containers, so a paused or restarting service counted as running, and `postgres`, `redis` and `prometheus` have no entrance probe to catch it a second way. Automatic restart is `restart: unless-stopped` plus `launchd/reconcile-port-bindings.sh`, which covers both the boot race that the restart policy provably does not and — since the 19:10 boot, where Docker restored nothing at all — the case of a stack that was never started. §1.1 round one has now passed five times in six attempts and round two once, failing. **Both of the reconciler's repair paths have now been exercised by a boot, and both by fault injection rather than by waiting.** The binding half ran on 2026-07-26 at 21:05:31, injected per runbook §1.1a (hold `tailscaled` down 90 seconds so Docker cannot win), because seven boots of margin measurement showed that rebooting for it is waiting for weather, not testing. The container bring-up half ran at 21:52:14 on the next boot, injected per runbook §1.1b (`launchd/stop-stack-once.sh`: stop the stack, reboot, and `restart: unless-stopped` keeps it stopped, which is the state the 19:09 boot left) — Docker Desktop restored none of the nine, the reconciler found the platform empty and brought it up, and the whole recovery finished 51 seconds into the boot. That injector needs no person at the machine because the host stays on the tailnet throughout, and it cost 1m36s of downtime end to end. Neither injection establishes that its fault occurs unaided: the binding race is evidenced by the 16:45 boot and Docker's restore failing by the 19:10 boot alone, whose cause is still unknown. What both do establish is the repair working at boot, with everything else on the machine moving at once — the part a hand test cannot reproduce. **What is missing is an external dead-man's switch**: a monitor on the host it watches cannot report that the host is off, so the heartbeat currently relies on a person noticing a mail that did not arrive
- [ ] UPS, and the FileVault `authrestart` procedure documented in the runbook.
      FileVault is off until this lands and this item is the trigger to enable it
      ([security.md](./architecture/security.md) §15.6)
- [~] SSH demoted to repair-only, verified by running normal operations entirely through the UI. The transport half is done: Tailscale SSH only, gated by the §3.4 `ssh` block with 12-hour re-authentication, and macOS Remote Login is off so nothing answers on the LAN. What remains is the behavioural half — actually running operations through the UI rather than a shell, which cannot be claimed until there has been a period of operation to observe
- [ ] Trivy, pip-audit, and pnpm audit in CI
- [x] **Scheduled GeoLite2 refresh.** `launchd/refresh-geolite2.sh` plus its plist, weekly on Wednesdays: download with the permanent licence key (`secrets/maxmind_license_key`), verify the mmdb before touching anything, replace atomically, and restart the two enforcing containers only when the file actually changed — geoip2 opens the database once at startup, so a swap alone changes nothing. A failed run keeps the old database serving, and a staleness warning at the top of each run turns a month of quiet failures into a loud one. Written 2026-07-30; **installing the plist waits on the licence key being placed in `secrets/`**
- [ ] **Keep `tailscaled.log` readable.** The ASUS peer broadcasts Dropbox LAN sync to UDP 17500 every 31 seconds; the ACL drops it correctly and logs a line each time — 389 lines and 111 KB by the end of 2026-07-26, on a machine that has been up for hours, not days. The ACL is not the problem. The cost is to the log that both the port-binding fault and the netmap-cache finding were discovered by reading, so this is about preserving a diagnostic surface rather than tidiness. Either stop the peer broadcasting into the tailnet, or accept the noise and add rotation so the useful boot-time lines are not buried
- [ ] Playwright coverage of critical paths: create an API key, edit a routing policy and observe gateway behaviour change, cancel a stream mid-generation
- [ ] Periodic access review

## Decisions

No open decisions block Phase 1.

Settled:

- Backend structure: full hexagonal architecture ([backend.md](./architecture/backend.md))
- Frontend component library: shadcn/ui ([frontend.md](./architecture/frontend.md))
- Gateway and admin split into separate containers; the admin entrances are two more ([security.md](./architecture/security.md) §1)
- Management authentication: Tailscale identity on the tailnet; invitation-only local accounts with mandatory TOTP on the public entrance. No external identity provider, and no account exists that an administrator did not create ([security.md](./architecture/security.md) §5)
- Public entrance: the existing openresty proxy plus the `*.rcsl.online` wildcard ([deployment.md](./architecture/deployment.md))
- Source restriction: application-layer country filter, Taiwan and Australia ([security.md](./architecture/security.md) §4.1)
- Gateway exposes an OpenAI-compatible API
- First capability: `chat`. First runtime: Ollama, native on the host
- Chat UI is served by the admin API, not the public gateway ([security.md](./architecture/security.md) §5.2)
- Single tenant through Phase 1 ([ARCHITECTURE.md](./ARCHITECTURE.md) §2.8)
- Images built on the Mac Studio; migrations as a one-shot service ([deployment.md](./architecture/deployment.md) §9)
- Accepted risks recorded in [security.md](./architecture/security.md) §15
