# RCSL AI Nexus: Architecture

## 0. Background and Goals

Treat the Mac Studio as a 24/7 AI server rather than a personal computer. This document defines the architecture behind the management platform, which is this repository's primary deliverable. The goals are:

- Runtimes (Ollama, MLX, vLLM, llama.cpp) and models (Qwen, GLM, Gemma, DeepSeek) can be swapped without changing the upper API or agent layers.
- Day to day operations (model lifecycle, service restarts, API key management, monitoring) happen through the web UI. SSH is reserved for repairs.
- Adding a second Mac or a GPU server means registering a new compute node, not rebuilding the platform.

Three phases (see [ROADMAP.md](./ROADMAP.md)):

1. Base infrastructure (Docker Compose, directory layout, Tailscale) on the Mac Studio.
2. **The extensible AI platform, which is this repository**: management UI, gateway, and the capability abstraction.
3. Operations automation (health checks, backups, monitoring).

This phase was developed on Windows and produced code and Compose definitions only; deployment happens via git pull plus `docker compose up`. Since 2026-07-26 the Mac Studio is itself both the development machine and the deployment: the first `docker compose up` ran that day and the platform has served since ([PROGRESS.md](./PROGRESS.md) 2026-07-26 and later record what each deploy proved). What remains unverified is the public entrance, which waits on the NTNU proxy administrator.

### 0.1 A hardware constraint that shapes everything

**Model runtimes run natively on the macOS host, not in Docker.**

Docker containers on macOS execute inside a Linux VM that has no access to Apple GPU or Metal. A containerised Ollama would fall back to CPU-only inference, and MLX cannot run inside a Linux container at all. Either outcome defeats the purpose of the hardware.

Consequences that run through the rest of these documents:

- Ollama and MLX are installed and supervised on the macOS host (launchd), bound to `127.0.0.1`.
- Containers reach them through `host.docker.internal`.
- Runtime hardening is done at the host level (dedicated service account, filesystem permissions, loopback binding) rather than through container primitives such as `cap_drop` or `read_only`.
- "Keep the host clean" from the original plan is achieved for everything except the runtimes.

### 0.2 The machine

The target host is a Mac Studio (M4 Max):

- 16-core CPU, 40-core GPU
- 64 GB unified memory
- 4 TB SSD
- 10 Gb Ethernet, Wi-Fi 6E (802.11ax), Bluetooth 5.3

Two of these numbers are load-bearing rather than incidental. The 64 GB is
unified across CPU and GPU, which is why the memory budget (`MemoryBudgetService`,
`NODE_TOTAL_MEMORY_GB=64`) governs model loads against a single figure rather
than a separate VRAM pool; that setting must match this number, since too high
drives the host into swap and too low refuses models that would fit. And the
inference concurrency cap (`MAX_CONCURRENT_INFERENCE=4`) is sized for one 40-core
GPU with no second compute node yet — it buys queueing depth rather than
throughput, since that one GPU serves a single generation at a time, and the
number tracks the peak number of simultaneous users rather than any property of
the hardware. The 10 Gb Ethernet is the wired path to the
NTNU proxy; the tailnet rides over it.

## 1. Layered Architecture

```
+-----------------------------------------------------------+
|  Application Layer                                          |
|  Open WebUI / custom agents / third-party applications      |
+---------------------------+-------------------------------+
                            | HTTP (OpenAI-compatible + admin API)
+---------------------------v-------------------------------+
|  Gateway                                                    |
|  - Unified public API (/v1/chat/completions,                |
|    /v1/responses, /v1/models)                               |
|  - API key authentication, rate limiting, usage accounting  |
|  - Selects a target runtime from capability + routing policy|
+---------------------------+-------------------------------+
                            |
+---------------------------v-------------------------------+
|  Capability Layer (abstraction)                             |
|  chat / code / vision / embedding / rerank                  |
|  Each capability maps to candidate models with priority     |
+---------------------------+-------------------------------+
                            |
+---------------------------v-------------------------------+
|  Model Registry                                             |
|  - Registered models (alias, ref, runtime, state, resources)|
|  - Download / load / unload state machine                   |
+---------------------------+-------------------------------+
                            |
+---------------------------v-------------------------------+
|  Model Runtime (swappable, runs on the macOS host)          |
|  Ollama / MLX / vLLM / llama.cpp                            |
+---------------------------+-------------------------------+
                            |
+---------------------------v-------------------------------+
|  Compute Node (hardware)                                    |
|  Mac Studio (initially the only node) / future GPU servers   |
+-----------------------------------------------------------+
```

The management platform spans the control plane of the Gateway, Capability, and Model Registry layers. It does not perform inference itself.

## 2. Core Concepts

### 2.1 Compute Node

A machine capable of running model runtimes.

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `name` | Display name, for example `mac-studio-01` |
| `address` | Tailscale address. Must fall inside the tailnet range, see [security.md](./architecture/security.md) §7.2 |
| `status` | `online` / `offline` / `degraded` |
| `runtimes` | Runtime kinds available on this node |
| `total_memory_gb` | Static capacity, used by the Phase 1 memory budget check |

Live metrics (CPU, memory, temperature) are not stored on the entity. They are read through `MetricsPort` in Phase 2.

### 2.2 Model

A model registered in the registry. Three different identifiers exist and are easy to confuse, so they are defined precisely here.

| Field | Notes |
|---|---|
| `id` | Internal UUID. Never exposed to API consumers |
| `alias` | Public name used by routing policies, for example `qwen-coder`. **Globally unique** |
| `ref` | Runtime-specific identifier, for example `qwen2.5-coder:32b`. **Unique per (runtime, node)** |
| `runtime` | `ollama` / `mlx` / `vllm` / `llamacpp` |
| `node_id` | Which compute node holds it |
| `state` | `not_downloaded` / `downloading` / `downloaded` / `loading` / `loaded` / `unloading` / `error` |
| `capabilities` | Which capabilities this model can serve |
| `resource_profile` | `{ memory_gb: float, context_length: int }` |

The distinction matters: routing policies bind to `alias` so that swapping the underlying model does not require editing every policy, while `ref` is what gets passed to the runtime adapter.

### 2.3 Capability

The unit that applications call against, deliberately decoupled from any specific model: `chat`, `code`, `vision`, `embedding`, `rerank`, and `assist`. Each capability resolves through exactly one routing policy.

There are **two** sets and they are defined together, in `domain/entities/capability.py`: `ISSUABLE_CAPABILITIES`, what a key may be issued for, and `ROUTABLE_CAPABILITIES`, the superset a policy may be written for. `assist` is routable and not issuable, so the management assistant can be pointed at a fast model without a key ever being sold access to an internal management surface ([security.md](./architecture/security.md) §7.5.1). Three places have to agree on them — a key is issued for capabilities, a policy is written for one, and the gateway maps one onto the scope that reaches inference — and until 2026-07-28 each kept its own copy, which had drifted in both directions at once ([PROGRESS.md](./PROGRESS.md) 2026-07-28).

**The name is what a caller puts in the `model` field**, which is the platform's one departure from the OpenAI convention and the thing an integrator is least able to guess. `GET /v1/models` exists to answer it, listing the capabilities a routing policy currently serves, narrowed to the calling key.

**Only chat-shaped capabilities are reachable today.** The gateway mounts `/v1/chat/completions` and `/v1/responses` and nothing else — the second added 2026-08-07 for agent clients that dropped Chat Completions, and a translation onto the same use case rather than a second inference path — so `embedding` and `rerank` can be named in a policy and issued on a key but have no endpoint whose request and response shapes fit them. They are part of the model, not yet part of the API; `/v1/embeddings` belongs with the knowledge base in Phase 2, which is the first thing that will need it.

### 2.4 Routing Policy

Maps a capability to candidate models with priority and fallback.

```jsonc
{
  "capability": "code",
  "candidates": [
    {
      "model_alias": "qwen-coder",
      "priority": 100,
      "require": { "node_status": ["online"], "model_state": ["loaded"] }
    },
    {
      "model_alias": "deepseek-coder-fallback",
      "priority": 10,
      "require": { "node_status": ["online"] }
    }
  ]
}
```

**`require` is a fixed structured document, never an expression string.** An earlier draft used a string such as `"node.status == online"`, which invites an implementation based on `eval()` or a small expression evaluator. Since routing policies are editable through the admin UI and evaluated inside the gateway process, that would turn "edit a routing policy" into "execute arbitrary code in the gateway". `RoutingService` must match the structured fields only. See [architecture/backend.md](./architecture/backend.md) §4.

### 2.5 API Key

Issued to applications and users. Binds allowed capabilities, rate limit, quota, expiry, and source CIDRs. Full design in [security.md](./architecture/security.md) §4.2.

The capability list is enforced against the capability each request names, and has been since 2026-07-28. Before that it decided only whether a key worked at all, so a key issued for `chat` reached every capability the deployment could route — the field read as a restriction and was not one. The names it may contain are `domain/entities/capability.py`, which is also what a routing policy is checked against, so a policy and a key cannot disagree about what a capability is called.

### 2.6 User

A human who can sign in to the management UI. Identity arrives from one of two sources, so the table carries both.

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `login` | Unique login, an email address in practice |
| `display_name` | |
| `tailscale_login` | Login as reported by Tailscale, nullable |
| `password_hash` | argon2id, nullable. Absent for tailnet-only users |
| `totp_secret` | Encrypted at rest, nullable. **Required whenever `password_hash` is set** |
| `totp_last_counter` | Replay prevention, see [security.md](./architecture/security.md) §5.3 |
| `role` | `admin` / `tenant_admin` / `operator` / `curator` / `auditor` / `user`. Not a ladder: `curator` writes knowledge `operator` may not touch, and `operator` restarts a node `tenant_admin` may not. A seventh, `service`, exists in the enum but belongs to an API key rather than a person and never appears in this table (`domain/entities/actor.py`) |
| `debug_logging_until` | Optional timestamp, see [security.md](./architecture/security.md) §9.2 |

Accounts are **invitation only**; there is no self-registration. A user who only ever works over the tailnet needs no password at all, so both credential columns are nullable. A user who needs the public entrance is issued a single-use invitation link and sets their own password and TOTP; the platform never transmits a credential. See [security.md](./architecture/security.md) §5.3 and §5.4.

Supporting tables: `invitations` (token hash, expiry, consumed timestamp) and `recovery_codes` (hashed, single use). Sessions live in Redis, not Postgres.

### 2.7 Actor

The runtime representation of "who is making this request", assembled by the interface layer and passed into use cases. It unifies the three authentication sources so that authorization logic has a single shape.

```python
@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    display: str                                  # login or key id, safe for logs
    role: Role                                    # one of the seven in §2.6
    source: Literal["tailnet", "local", "api_key", "dev"]
    scopes: frozenset[Scope]

    tenant_id: str = DEFAULT_TENANT_ID            # §2.8; the tenant-scoped
                                                  #   repositories are built with it
    api_key_id: str | None = None                 # the key handle when source is
                                                  #   api_key; usage accounting and
                                                  #   the per-key quota both key on it
    allowed_capabilities: frozenset[str] | None = None
    default_capability: str | None = None         # what serves a capability this key
                                                  #   was not issued for; None refuses
    debug_logging_until: datetime | None = None   # §9.2's window, carried here so the
                                                  #   application layer can read it
```

`allowed_capabilities` is deliberately not expressed as scopes. `Scope.CHAT_USE`
answers "may this caller reach inference at all" and is drawn from a hardcoded
table no database row can widen; *which* capability is then asked for is data,
chosen per request, so it travels here and is checked where the capability is
read. `None` is unrestricted and belongs to a person on an admin entrance; a set
belongs to an API key, and an empty one permits nothing.

`default_capability` is the one exception to the refusal that follows from an
empty answer, and it is a substitution rather than a widening. `capability_for`
re-checks the stored value against `allowed_capabilities` rather than trusting
it, so a row written by some other hand still reaches nothing the key was not
issued for; `None`, the default, refuses as before.

### 2.8 Tenancy: single tenant in Phase 1, multi-tenant foundation in Phase 2

Phase 1 was **single tenant** and said so, deliberately: an earlier draft described tenant-scoped filtering in the knowledge base repository, implying an isolation boundary that no entity, table, or migration actually provided, and a claimed boundary that does not exist is worse than none because it stops people from looking for the risk.

**The boundary now exists (Phase 2).** A `Tenant` entity, a `tenant_id` on `users`, `api_keys`, `usage_records`, `audit_log`, `prompt_logs` (2026-08-08) and `refusals` (2026-08-18), and tenant-scoped repositories that filter every read and stamp every write from the actor's tenant, inside the adapter so a use case cannot forget it. `models`, `nodes` and `routing_policies` carry no tenant: they are the shared compute the tenants use. Scope so far is the foundation plus minimal management (create and list tenants). **The knowledge base was built on 2026-07-30 and does plug into this boundary**, enforcing it in three further places: `knowledge_collections` and `knowledge_documents` both carry `tenant_id` and are filtered on it directly, the document storage adapter puts the tenant in the path, and the vector store puts it in the Qdrant collection name — so a search that lost its tenant names a collection that does not exist rather than reading everyone's passages. One read sits outside the boundary and is named in §7.3: ingestion job progress, whose cache entry carries no tenant. See [security.md](./architecture/security.md) §7.3 and [ROADMAP.md](./ROADMAP.md).

### 2.9 Prompt Template (Phase 2, built 2026-08-05)

A named system prompt, tenant-scoped, that a caller selects by name with `"prompt_template"` on the gateway and the admin chat alike. It is inserted whole at the front of the conversation, ahead of any system message the caller sent, which is kept.

| Field | Notes |
|---|---|
| `id` | Internal UUID |
| `tenant_id` | Tenant data, like the knowledge base and unlike models or nodes |
| `name` | What a caller writes in the request. **Unique per tenant**, not globally — a global constraint would refuse a name because another tenant had taken it, and report that they exist |
| `description` | For whoever is choosing one. Never sent to a model |
| `system_prompt` | Sent verbatim. Bounded at 8000 characters, a resource guardrail rather than a security one: the context ceiling is shared with the conversation, the tool definitions and any retrieved passages |

**There is no variable substitution, and that is the design.** A template body is the one message the model treats as authoritative, so a slot in it filled from a request would let a caller write into it — an escalation from asking questions to giving instructions. What a caller chooses is *which* template, not what it says. The full reasoning, and the shape a per-request value would have to take instead, is in [security.md](./architecture/security.md) §7.4.

## 3. Management Modules

Frontend pages correspond to backend resources. Phase annotations show what actually exists when.

This table said "None of the admin API exists yet" and marked almost every row
"frontend only" until 2026-07-28, by which point every row it then carried,
except the knowledge base and prompt templates, had been built and exercised
against a real Postgres. Everything below those two postdates that reading. The Phase column is a plan;
the Built column is a status, and a status that is only ever written once is
worse than none. [ROADMAP.md](./ROADMAP.md) and
[PROGRESS.md](./PROGRESS.md) are the maintained versions.

| Module | Backend resource | Phase | Built |
|---|---|---|---|
| Dashboard | `/admin/dashboard` | 1 (counts), 2 (real metrics) | yes; live metrics wait on hardware producing them |
| Model Management | `/admin/models` | 1 | yes, end to end including download progress (`GET /admin/download-jobs/{job_id}`, on the same router that starts the download) |
| Routing Policy | `/admin/routing-policies` | 1 (API), 2 (UI editor) | yes, both; the capability named is validated against `ROUTABLE_CAPABILITIES`, the wider of the two sets — a policy may be written for something no key can be issued for ([security.md](./architecture/security.md) §7.5.1) |
| API Keys | `/admin/api-keys` | 1 | yes, end to end: issue, edit, revoke |
| Gateway information | `/admin/gateway` | 1 | yes; the base URL and servable capabilities the UI needs to explain a key |
| Users and roles | `/admin/users`, `/admin/me` | 1 | yes, end to end |
| Tenants | `/admin/tenants` | 2 | yes, create and list; no platform-super-admin split |
| Chat | `/admin/chat` | 1 | yes, end to end |
| Node management | `/admin/nodes` | 2 | yes, end to end (register/edit/delete/health, SSRF guard, heartbeat) |
| Logs | `/admin/logs` | 2 | yes, read-only audit view behind `logs:read` |
| Usage analytics | `/admin/usage` | 2 | yes, aggregation and charts |
| Knowledge base | `/admin/knowledge` | 2 | yes, built 2026-07-30: collections, upload, isolated extraction in the `parser` container, Qdrant passage index, and tenant isolation enforced in three further places (§2.8) |
| Prompt templates | `/admin/prompt-templates` | 2 | yes, end to end: authored in the UI, selected by name on both chat paths. **No variable substitution**, deliberately — §7.4's rule is that values go in their own slot rather than into a template body, and a slot filled from a request would let a caller write into the one message the model treats as authoritative ([security.md](./architecture/security.md) §7.4) |
| Transcripts | `/admin/prompt-logs` | 2 | yes, read-only. Behind `prompt_log:read`, which is admin-only and withheld from `tenant_admin`: this reads what somebody typed, not that they typed ([security.md](./architecture/security.md) §9.2) |
| Refusals | `/admin/refusals` | 2 | yes, built 2026-08-18. Every `DomainError` is stored where its caller can read it; `refusal:read_own` is a base scope, `refusal:read_all` is granted like `usage:read_all` ([security.md](./architecture/security.md) §9.5) |
| Retention | `/admin/retention` | 2 | yes: per-dataset policy, preview and purge, behind `retention:write`. Admin-only, because a tenant administrator who could purge could remove the record of what they did inside their own tenant |
| Host status | `/admin/host` | 2 | yes; free memory, disk, uptime and load, read from `launchd/host-metrics.py` over loopback rather than from inside a container, which on macOS would describe the Linux VM (§0.1) |
| Model evaluation | `/admin/evaluations` | 2 | yes, shipped 2026-08-17 |
| Management assistant | `/admin/assistant` | 2 | yes, and **advisory only**: it answers about this deployment's settings and may propose values on the two key forms, never apply them. Routes on `assist`, which is routable but deliberately not issuable ([security.md](./architecture/security.md) §7.5, §7.5.1) |
| API reference | none; the page is served by the frontend | 2 | yes — the documentation §4.4 promises in exchange for disabling `/openapi.json` in production |
| Connect an agent | none; the page is served by the frontend | 2 | yes; the setup an agent client needs, alongside [runbooks/connect-an-agent-client.md](./runbooks/connect-an-agent-client.md) |

The inference path is complete and tested end to end. The gateway mounts
`POST /v1/chat/completions`, `POST /v1/responses` and `GET /v1/models`, and
nothing else — the third because every OpenAI client library calls it at
startup, and because `model` takes a capability rather than a model name, which
is a convention no caller guesses and which `/openapi.json` cannot tell them
either (it is disabled in production,
[security.md](./architecture/security.md) §4.4). `/v1/responses` landed
2026-08-07 for agent clients that dropped Chat Completions; it translates onto
the same `RouteChatRequest`, so routing, quota, rate limiting, the resource
guardrails, cancellation and usage recording are the ones already in force.

The chat interface lives on the admin API rather than calling the public gateway. It reuses the same `RouteChatRequest` use case but authorizes by user identity instead of an API key, so operators do not need to mint a key for themselves and admin traffic is not subject to the public geo and CIDR restrictions. The same resource guardrails still apply. See [security.md](./architecture/security.md) §5.2.

## 4. Technology Choices

- Backend (gateway and admin API): **Python + FastAPI**
- Frontend (management UI): **Next.js (React) + shadcn/ui**
- State: PostgreSQL (registry, policies, keys, users, usage, audit)
- Cache and job state: Redis (rate limits, session storage, model download progress)
- Vector store: Qdrant (knowledge base). Reached over its REST API rather than through `qdrant-client`, which would pull grpcio and protobuf into an image that needs neither; see `adapters/vector/qdrant_store.py`
- Document storage: **a mounted volume, not MinIO (decided while building the knowledge base)**. MinIO was the original plan and was dropped on contact with the deployment. It is another service to run, another set of default credentials to replace (`minioadmin`/`minioadmin`, named in [security.md](./architecture/security.md) §10) and another CVE surface, and what it would have bought — presigned URLs, per-tenant credentials, storage that outlives one machine — none of it is used by a single-node deployment with one filesystem. Documents live under `/var/lib/nexus/documents/<tenant>/<document>/` on a Docker volume, with keys derived from ids the platform generates so no caller ever supplies a path. **A second compute node is the trigger to revisit this**: the moment two machines must read the same documents, a volume stops being sufficient and MinIO (or an equivalent) becomes the answer again
- Monitoring: Prometheus + Grafana (Phase 2), consumed by the dashboard rather than reimplemented

**The gateway and admin API are separate containers (decided).** The reasoning is a security requirement rather than a code-structure preference; see [architecture/security.md](./architecture/security.md) §1.

- `gateway`: data plane, `/v1/*`, reachable from the public internet through an external reverse proxy, authenticated by API key.
- `admin-tailnet`: control plane over the tailnet, authenticated by Tailscale identity.
- `admin-public`: control plane over the public internet, authenticated by an invitation-only local account with mandatory TOTP.
- `parser`: document extraction for the knowledge base. The same image running a different ASGI app (`app.parser.main`), on an isolated network with no database, no secrets and no egress at all, because it is the one process that reads a file a person uploaded. See [architecture/security.md](./architecture/security.md) §7.3.
- `frontend-tailnet` and `frontend-public`: the Next.js application, one instance per entrance from one image, differing only in which admin API the middleware rewrite targets. Two rather than one for the same reason the admin API is two: an entrance that trusts a Tailscale header must not share a socket with one reachable from the internet.

Five containers run from the backend image: those three, `parser`, and the one-shot `migrate` job. The three application entrances share the entire `domain/` and `application/` layers, and only the routers mounted by `interfaces/http` differ, so splitting them costs no duplicated code. `parser` shares the image rather than the layers — the isolation that matters there is the process, network and credential boundary, not which layers the code was built from.

Detailed internal design:

- [architecture/backend.md](./architecture/backend.md): hexagonal architecture, ports and adapters, streaming contract, error mapping, testing
- [architecture/frontend.md](./architecture/frontend.md): component layering, generated types, data flow, auth modes
- [architecture/security.md](./architecture/security.md): threat model, network design, API key scheme, high-risk features, accepted risks
- [architecture/deployment.md](./architecture/deployment.md): physical topology, entrances, nginx configuration, build and upgrade, local development

## 5. Decisions

No open decisions block Phase 1.

Settled:

- **OpenAI-compatible API format**: yes. The gateway exposes `/v1/chat/completions` and friends so existing tooling connects without a shim.
- **First capability to complete end to end**: `chat`.
- **First runtime**: Ollama, running natively on the macOS host.
- **Model downloads use each runtime's HTTP API, never a shell.** Where a runtime offers only a CLI, it must be invoked with an argument array and `shell=False` after validating the model reference. See [security.md](./architecture/security.md) §7.1, the highest-risk feature in the system.
- **Authentication**: dual entrance for the admin UI (Tailscale identity on the tailnet; invitation-only local accounts with mandatory TOTP on the public internet); API keys for the gateway. There are six roles for people — `admin`, `tenant_admin`, `operator`, `curator`, `auditor`, `user` — plus `service` for an API key; they do not nest, and §2.6 records why the operator/administrator split is the one that matters most. No external identity provider is involved, and no account exists that an administrator did not create. See [security.md](./architecture/security.md) §5.
- **Public entrance**: the existing openresty reverse proxy at NTNU, forwarding over the tailnet, using the existing `*.rcsl.online` wildcard. See [deployment.md](./architecture/deployment.md).
