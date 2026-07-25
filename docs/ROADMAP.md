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
| `/v1/chat/completions`, streaming and not | Complete, tested end to end against a real Postgres |
| Routing, registry, keys, usage: persistence | Complete, migrations tested |
| Ollama adapter, reference validation | Complete |
| Gateway security: scopes, quota, rate limit, CIDR, geo, guardrails | Complete |
| Local accounts, TOTP, sessions, CSRF, bootstrap | Complete, tested from a fresh deployment to a signed-in user |
| Both admin entrances: identity resolution, `/me` | Complete. Each installs its own resolver; neither can default to the other's |
| Invitation and password reset flows, both ends | Complete |
| Audit logging | Adapter written, and every administrative action records one |
| Admin API: models, downloads, routing policies, API keys, users, dashboard, `/admin/chat` | Complete, exercised end to end against a real Postgres |
| Node management | Read only. The single node is named in configuration; a write endpoint ships with the SSRF guard ([security.md](./architecture/security.md) §7.2) |
| Database account split, Docker secrets in Compose | Complete. Three least-privilege Postgres accounts provisioned by `migrate`; all credentials mounted as Docker file secrets. Proven against a live Postgres 17 (`tests/integration/test_db_role_grants.py`) and by a full `ENV=production` Compose smoke test on the dev machine: `migrate` provisions the roles, each service connects as its own account, and the gateway is refused an `api_keys` write. Only the Mac-specific bits (GeoLite2, GPU, `tailscale serve`, nginx) remain unexercised |
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
- [x] `application/use_cases`: `RouteChatRequest`, `AuthenticateLocal`, `AcceptInvitation`, `IssueInvitation`, `ManageOwnAccount`, `BootstrapFirstAdmin`, `ManageModels`, `DownloadModel`, `ManageApiKeys`, `ManageUsers`, `ManageRoutingPolicies`, `ReadDashboard`
- [x] `interfaces/http/errors.py`: single exception handler, OpenAI envelope on the gateway, plain shape on admin
- [x] Routers: `chat`, `admin_chat`, `models`, `routing_policies`, `api_keys`, `users`, `auth`, `me`, `invitations`, `jobs`, `dashboard`, `health`
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
- [x] `next.config.js` rewrites so `/admin/*` is same-origin
- [x] `components/ui`: Button, Input, Table, Dialog, Badge, Tabs, Toast
- [x] `features/models`: node selection, now that `GET /nodes` exists
- [ ] `lib/generated`: `openapi-typescript` against the **admin** port (the gateway serves no schema)
- [x] `features/routing-policies`: table plus a candidate editor (per-capability, `useFieldArray` over candidates, structured requirement checkboxes), so a policy is no longer edited with curl
- [x] `lib/session.tsx`: consumes `/admin/me`, exposes `auth_mode` through context
- [x] `lib/api-client.ts`: `credentials: 'include'`, automatic CSRF header on mutations, 401 handling that branches on `auth_mode`
- [x] `components/composed`: `DataTable`, `StatCard`, `FormField`, `ConfirmDialog`, `StatusBadge`, `StreamMessage`, `EmptyState`, `ErrorState`
- [x] `features/models`: table, form dialog, download progress via `useDownloadJob`
- [x] `features/chat`: SSE consumption with abort on unmount, terminal error frames surfaced
- [x] `features/users`: list, invite (copyable single-use link), role change
- [x] `features/auth`: two-step login, invitation acceptance with TOTP QR and recovery codes, password change
- [x] `features/api-keys`
- [x] `features/dashboard`: static data for now
- [x] Markdown rendering sanitised, raw HTML disabled
- [x] Vitest unit coverage of the logic where a defect is a security defect: `safe-redirect` (open redirect), the chat SSE schema and reader (envelope parsing, error and truncation frames), `api-client` (CSRF header, 401 handling, no `Authorization`), and the password schema
- [ ] Component and E2E coverage (Playwright, listed in Phase 3): the sign-in and enrolment screens are not yet driven through a browser

### Infrastructure

- [x] `docker-compose.yml`: `gateway`, `admin-tailnet`, `admin-public`, `frontend-tailnet`, `frontend-public`, `postgres`, `redis`, `migrate`
- [x] Networks `app` and `data` (`data` is `internal: true`); no service publishes on `0.0.0.0`
- [x] `migrate` as a one-shot service; all applications gate on `service_completed_successfully`
- [ ] `tailscale serve` for the tailnet entrance
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
- [x] Tailscale ACL including `tag:ntnu-proxy`, so members cannot bypass the proxy
- [x] Trusted-proxy client address resolution using the shared secret header, not peer IP
- [x] Country filter on **both** the gateway and the public admin entrance
- [x] Per-key CIDR allowlists
- [x] API keys: HMAC with pepper, random `key_id` lookup, scopes, mandatory expiry, immediate revocation
- [x] Local accounts: argon2id, zxcvbn strength check, no user enumeration, escalating rate limits rather than hard lockout
- [x] TOTP mandatory at enrolment, with counter replay prevention and single-use recovery codes
- [x] Invitation and reset links: single use, hashed at rest, expiring; the platform never transmits a password
- [x] Server-side sessions in Redis, `__Host-` cookies, id rotation on login, invalidation on password change, CSRF double-submit
- [x] First-admin bootstrap, tailnet entrance only, inert once users exist
- [x] Separate database accounts; gateway cannot write `api_keys` or `users` (`infrastructure/db_roles.py`, provisioned by `migrate`)
- [~] Default credentials replaced: Redis, Postgres and now Grafana take real values from Docker file secrets (Grafana with anonymous access and self-registration disabled); Qdrant and MinIO arrive with the knowledge base in Phase 2
- [x] Model reference validation; no shell string construction anywhere
- [ ] Host runtime hardening: service account, `127.0.0.1` binding, directory ownership
- [x] **Resource guardrails: concurrency cap, `max_tokens`, context bound, per-read timeout, wall-clock generation deadline, cancel on disconnect.** With no edge protection these are the only defence. All enforced in `RouteChatRequest`; the concurrency slot spans the whole generator and disconnect cancellation propagates to the adapter (backend.md §6). The wall-clock deadline is the last piece: a slow-but-steady stream that stays under the per-read timeout yet never reaches the token cap would otherwise hold a slot for hours on unified memory near swap. Verified by unit tests against an injected clock; real GPU behaviour still waits for the Mac Studio, the same boundary inference has
- [x] `AuditPort` adapter, and auditing for bootstrap, invitations, resets, credential changes, key issuance and revocation, model registration, download and load, role changes and account removal
- [x] gitleaks pre-commit hook

## Phase 2: Full Management Functionality

- [x] Second runtime adapter (MLX), proving swappability without touching use cases or interfaces. Done: one adapter file plus three wiring points (`build_runtimes`, one setting, one Compose mount); `application/use_cases` and `interfaces` untouched, domain untouched. The layering held. What it surfaced is recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25: MLX has no download-with-progress endpoint (so `pull` downloads via `huggingface_hub` into a host-shared cache) and no unload (so `unload` refuses rather than desyncing the memory budget). Real MLX inference and a real download still wait for the Mac Studio, the same boundary Ollama inference has. vLLM stays deferred until there is NVIDIA/Linux hardware it runs on
- [x] Routing policy editor UI, including fallback configuration (the ordered candidate list with per-candidate priority and requirements is the fallback mechanism; shipped in Phase 1)
- [x] Node management UI, `NodeHealthPort`, heartbeats, and the SSRF guard shipping alongside the first node write endpoint. Done: `adapters/http/egress_guard.py` validates every node address against the tailnet range at write time (the rule in [security.md](./architecture/security.md) §7.2 that a write path may exist only with the guard); `NodeHealthPort` plus a heartbeat in the admin app replace the always-`online` assumption so a `node_status: [online]` requirement reflects reality; `ManageNodes` + `routers/nodes.py` carry register/edit/delete/check with attached-model and duplicate-name guards and audit; the frontend `features/nodes` screen shows live status. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25. Real runtime probing waits for the Mac Studio
- [x] Multi-tenancy: `Tenant` entity, `tenant_id` columns, repository-enforced query filters. Done as the foundation plus minimal management: `users`, `api_keys`, `usage_records` and `audit_log` carry `tenant_id` (models/nodes/routing stay platform-global), the tenant-scoped repositories filter reads and stamp writes from the actor's tenant (injected in the di builder, never taken from the caller, per [security.md](./architecture/security.md) §7.3), and identity/bootstrap use an explicit unscoped variant. `ManageTenants` creates tenants (minting a first-admin invitation into the new tenant) and lists them. Isolation is pinned by an integration test against real Postgres. No platform-super-admin split yet; recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25
- [x] Logs UI. Done: a read-only, admin-only audit view (`logs:read`) over the append-only `audit_log`, server-paged with action and outcome filters. A tenant-scoped read repository (`PostgresAuditLogRepository`) plus `ReadAuditLog` on the backend, `features/logs` on the frontend. Tenant isolation of the read is pinned against real Postgres. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25
- [x] Usage analytics with charts. Done, and the chart-library question is settled: no library. The data is simple magnitude-over-time, so the charts are inline SVG (`components/composed/metric-chart.tsx`, geometry in `chart-geometry.ts`), theme-aware through the `--chart-1..5` ramp, which sidesteps the Tremor/Recharts supply-chain and React 19 concerns entirely ([frontend.md](./architecture/frontend.md) §7). Backend: a `date_trunc` aggregation (`bucketed_usage`) and `ReadUsageAnalytics` behind `usage:read_all`, with `GET /admin/usage`; frontend: `features/usage` plus real series wired into the dashboard's two charts. The bucketing is verified against real Postgres. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25
- [x] Prometheus and Grafana, the emission side. Done: `/metrics` on all three apps behind a bearer-token guard (`adapters/metrics/prometheus.py`, `interfaces/http/middleware/metrics.py`, `interfaces/http/routers/metrics.py`); HTTP series via a streaming-safe pure-ASGI middleware, inference series derived from the existing `UsageRecord` through a `MeteredUsageRepository` (so the streaming use case is untouched), and a scrape-time concurrency-slot gauge. Prometheus and Grafana are on internal-only networks (`docker-compose.yml`, `prometheus/`, `grafana/`), Prometheus publishes no port, Grafana's password is a file secret with anonymous access and self-registration off. Recorded in [PROGRESS.md](./PROGRESS.md) 2026-07-25. **Live metrics replacing the static memory budget is deliberately not done**: the `MetricsPort` figure the budget reads is a real free-memory number only on the Mac Studio, so the budget stays static and authoritative until then ([security.md](./architecture/security.md) §4.3)
- [ ] `MetricsPort` ingestion: a live free-memory figure feeding the memory budget, once there is hardware producing a real one
- [ ] Knowledge base with Qdrant, isolated document parsing, upload validation
- [ ] Prompt template management
- [ ] Logging boundaries and the expiring debug switch on both keys and users
- [ ] Full audit coverage across every event in [security.md](./architecture/security.md) §12
- [ ] Authorization checks covering every use case
- [ ] Encrypted backups and a rehearsed restore
- [ ] Storybook stories for `components/composed`

## Phase 3: Operations and Multi-Node

- [ ] Second compute node registered and serving
- [ ] Automatic restart and health alerting
- [ ] UPS, and the FileVault `authrestart` procedure documented in the runbook
- [ ] SSH demoted to repair-only, verified by running normal operations entirely through the UI
- [ ] Trivy, pip-audit, and pnpm audit in CI
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
