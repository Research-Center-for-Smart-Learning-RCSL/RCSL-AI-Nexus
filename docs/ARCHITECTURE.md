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

This phase was developed on Windows and produced code and Compose definitions only; deployment happens via git pull plus `docker compose up`. Since 2026-07-26 the Mac Studio is itself the development machine, so the local development mode described in [architecture/deployment.md](./architecture/deployment.md) is no longer the only way the code is exercised — but the first deploy has not been done, and everything needing the stack up remains unverified.

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
inference concurrency cap (`MAX_CONCURRENT_INFERENCE`) is sized for one 40-core
GPU with no second compute node yet. The 10 Gb Ethernet is the wired path to the
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
|  - Unified public API (/v1/chat/completions, /v1/embeddings)|
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

The unit that applications call against, deliberately decoupled from any specific model: `chat`, `code`, `vision`, `embedding`, `rerank`. Each capability resolves through exactly one routing policy.

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
| `role` | `admin` / `user` |
| `debug_logging_until` | Optional timestamp, see [security.md](./architecture/security.md) §9.2 |

Accounts are **invitation only**; there is no self-registration. A user who only ever works over the tailnet needs no password at all, so both credential columns are nullable. A user who needs the public entrance is issued a single-use invitation link and sets their own password and TOTP; the platform never transmits a credential. See [security.md](./architecture/security.md) §5.3 and §5.4.

Supporting tables: `invitations` (token hash, expiry, consumed timestamp) and `recovery_codes` (hashed, single use). Sessions live in Redis, not Postgres.

### 2.7 Actor

The runtime representation of "who is making this request", assembled by the interface layer and passed into use cases. It unifies the three authentication sources so that authorization logic has a single shape.

```python
@dataclass(frozen=True)
class Actor:
    id: str
    display: str                                  # login or key prefix, safe for logs
    role: Role                                    # admin / user / service
    source: Literal["tailnet", "local", "api_key"]
    scopes: frozenset[Scope]
```

### 2.8 Tenancy: single tenant in Phase 1, multi-tenant foundation in Phase 2

Phase 1 was **single tenant** and said so, deliberately: an earlier draft described tenant-scoped filtering in the knowledge base repository, implying an isolation boundary that no entity, table, or migration actually provided, and a claimed boundary that does not exist is worse than none because it stops people from looking for the risk.

**The boundary now exists (Phase 2).** A `Tenant` entity, a `tenant_id` on `users`, `api_keys`, `usage_records` and `audit_log`, and tenant-scoped repositories that filter every read and stamp every write from the actor's tenant, inside the adapter so a use case cannot forget it. `models`, `nodes` and `routing_policies` carry no tenant: they are the shared compute the tenants use. Scope so far is the foundation plus minimal management (create and list tenants); the knowledge base plugs into this boundary when it is built. See [security.md](./architecture/security.md) §7.3 and [ROADMAP.md](./ROADMAP.md).

## 3. Management Modules

Frontend pages correspond to backend resources. Phase annotations show what actually exists when.

**None of the admin API exists yet.** Both admin applications currently mount
only `/healthz` and `/readyz`; the frontend for these modules is written and
calls endpoints that return 404. The Phase column is a plan, not a status.

| Module | Backend resource | Phase | Built |
|---|---|---|---|
| Dashboard | `/admin/dashboard` | 1 (static data), 2 (real metrics) | frontend only |
| Model Management | `/admin/models` | 1 | frontend only |
| Routing Policy | `/admin/routing-policies` | 1 (API), 2 (UI editor) | no |
| API Keys | `/admin/api-keys` | 1 | frontend only |
| Users and roles | `/admin/users`, `/admin/me` | 1 | frontend only |
| Chat | `/admin/chat` | 1 | frontend only |
| Node management | `/admin/nodes` | 2 | yes, end to end (register/edit/delete/health, SSRF guard, heartbeat) |
| Logs | `/admin/logs` | 2 | no |
| Usage analytics | `/admin/usage` | 2 | no |
| Knowledge base | `/admin/knowledge` | 2 | no |
| Prompt templates | `/admin/prompt-templates` | 2 | no |

The inference path (`/v1/chat/completions`) is complete and tested end to end.

The chat interface lives on the admin API rather than calling the public gateway. It reuses the same `RouteChatRequest` use case but authorizes by user identity instead of an API key, so operators do not need to mint a key for themselves and admin traffic is not subject to the public geo and CIDR restrictions. The same resource guardrails still apply. See [security.md](./architecture/security.md) §5.2.

## 4. Technology Choices

- Backend (gateway and admin API): **Python + FastAPI**
- Frontend (management UI): **Next.js (React) + shadcn/ui**
- State: PostgreSQL (registry, policies, keys, users, usage, audit)
- Cache and job state: Redis (rate limits, session storage, model download progress)
- Vector store: Qdrant (knowledge base, Phase 2)
- Object storage: MinIO (uploaded documents, Phase 2)
- Monitoring: Prometheus + Grafana (Phase 2), consumed by the dashboard rather than reimplemented

**The gateway and admin API are separate containers (decided).** The reasoning is a security requirement rather than a code-structure preference; see [architecture/security.md](./architecture/security.md) §1.

- `gateway`: data plane, `/v1/*`, reachable from the public internet through an external reverse proxy, authenticated by API key.
- `admin-tailnet`: control plane over the tailnet, authenticated by Tailscale identity.
- `admin-public`: control plane over the public internet, authenticated by an invitation-only local account with mandatory TOTP.
- `frontend`: the Next.js application.

All backend containers run from the same image and share the entire `domain/` and `application/` layers. Only the routers mounted by `interfaces/http` differ, so splitting them costs no duplicated code.

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
- **Authentication**: dual entrance for the admin UI (Tailscale identity on the tailnet; invitation-only local accounts with mandatory TOTP on the public internet); API keys for the gateway. Roles are `admin` and `user`. No external identity provider is involved, and no account exists that an administrator did not create. See [security.md](./architecture/security.md) §5.
- **Public entrance**: the existing openresty reverse proxy at NTNU, forwarding over the tailnet, using the existing `*.rcsl.online` wildcard. See [deployment.md](./architecture/deployment.md).
