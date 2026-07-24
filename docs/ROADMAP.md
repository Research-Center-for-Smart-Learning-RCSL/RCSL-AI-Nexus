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
| Audit logging | Adapter written and called by the authentication flows. Nothing else is audited, because nothing else exists |
| **The rest of the admin API** | **Not started.** Models, routing policies, API keys, jobs, dashboard, `/admin/chat`. `/users` has listing and link issuing only |
| Database account split, Docker secrets in Compose | Not started |
| Frontend | Sign-in, invitation acceptance and password reset now reach a real backend. Everything else still calls endpoints that 404. No test runner |

### Backend: hexagonal skeleton

- [x] Five layers: `domain` / `application` / `adapters` / `interfaces` / `infrastructure`
- [x] `domain/entities`: `Model`, `Node`, `Capability`, `RoutingPolicy`, `ApiKey`, `User`, `Actor`, `UsageRecord`
- [x] `domain/services`: `RoutingService` (structured requirement matching, **never expression evaluation**), `MemoryBudgetService`, `ApiKeyService`, `TokenService`, `LoginThrottle`
- [x] `domain/ports`: runtime, repositories (model, node, policy, api key, user, usage), authorization, audit, cache, job progress
- [x] `domain/exceptions.py`: `DomainError` hierarchy with `code` and `public_message`
- [x] `adapters/runtime/ollama_adapter.py` plus `validation.py` for model reference parsing
- [x] `adapters/persistence/`: Postgres implementations, ORM models kept separate from entities
- [x] `adapters/authz`, `adapters/audit`, `adapters/cache`, `adapters/crypto`, `adapters/session`
- [x] `application/use_cases`: `RouteChatRequest`, `AuthenticateLocal`, `AcceptInvitation`, `IssueInvitation`, `ManageOwnAccount`, `BootstrapFirstAdmin`
- [ ] `application/use_cases`: `RegisterModel`, `DownloadModel`, `LoadModel`, `UnloadModel`, `CreateApiKey`, `RevokeApiKey`, `SetUserRole`
- [x] `interfaces/http/errors.py`: single exception handler, OpenAI envelope on the gateway, plain shape on admin
- [x] Routers: `chat`, `auth`, `me`, `invitations`, `health`; `users` partially (list and link issuing)
- [ ] Routers: `admin_chat`, `models`, `routing_policies`, `api_keys`, `jobs`, `dashboard`, and the rest of `users`
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
- [ ] `lib/generated`: `openapi-typescript` against the **admin** port (the gateway serves no schema)
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
- [ ] Separate database accounts; gateway cannot write `api_keys` or `users`
- [ ] Default credentials replaced: Redis, Qdrant, MinIO, Grafana, Postgres
- [x] Model reference validation; no shell string construction anywhere
- [ ] Host runtime hardening: service account, `127.0.0.1` binding, directory ownership
- [ ] **Resource guardrails: concurrency cap, `max_tokens`, timeout, cancel on disconnect.** With no edge protection these are the only defence
- [x] `AuditPort` adapter, and auditing for bootstrap, invitation, reset and credential changes
- [ ] Auditing for key issuance and revocation and for model download and load, which arrives with those endpoints
- [x] gitleaks pre-commit hook

## Phase 2: Full Management Functionality

- [ ] Second runtime adapter (vLLM or MLX), proving swappability without touching use cases or interfaces
- [ ] Routing policy editor UI, including fallback configuration
- [ ] Node management UI, `NodeHealthPort`, heartbeats, and the SSRF guard shipping alongside the first node write endpoint
- [ ] Multi-tenancy: `Tenant` entity, `tenant_id` columns, repository-enforced query filters
- [ ] Logs UI
- [ ] Usage analytics with charts (confirm the chart library before building)
- [ ] `MetricsPort` with Prometheus and Grafana; live metrics replace the static memory budget
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
