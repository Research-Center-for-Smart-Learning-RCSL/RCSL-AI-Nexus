# Backend Architecture: Hexagonal (Ports and Adapters)

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md). Defines the internal layering of the FastAPI project.

## 1. Why Hexagonal

The requirement itself demands dependency inversion: runtimes must be swappable without touching the API or agent layers. Hexagonal architecture turns that sentence into a structural rule rather than a matter of developer discipline.

- `domain` knows nothing about FastAPI, SQLAlchemy, or Ollama. It only knows the ports it defines.
- `adapters` implement those ports and handle all contact with the outside world.
- Dependencies always point inward: `interfaces -> application -> domain`. Adapters implement `domain.ports`, but `domain` never imports adapters.

A concrete payoff specific to this project: the gateway and the two admin entrances are three separate containers that share the entire `domain/` and `application/` layers. Only the mounted routers differ. Splitting them for security reasons (see [security.md](./security.md) §1) costs no duplicated code.

## 2. Folder Structure

**This is the target layout, not the current one.** Two deliberate departures
have already happened and are worth stating rather than leaving as apparent
drift: the individually named port files are consolidated into `repositories.py`,
`security_ports.py` and `infrastructure_ports.py`, and the per-entity
`postgres_*_repository.py` files into a single `repositories.py`. The protocols
and classes all exist under those names; only the file granularity differs.

The third departure is naming. The use cases below were sketched one verb per
file; they were written one *subject* per file, because the verbs share their
guards — `ManageApiKeys` holds create, update and revoke together precisely so
that the owner-permission check cannot be applied to two of them and forgotten
on the third. So `create_api_key.py` and `revoke_api_key.py` are
`manage_api_keys.py`, and the same for models, nodes, users, tenants and
routing policies.

This paragraph used to say that everything under `application/use_cases/` other
than `route_chat_request.py` and `authenticate_local.py` was unwritten, and that
every router except `chat.py` and `health.py` was too. That stopped being true
during Phase 1 and was still here on 2026-07-28. What exists now is every use
case and every router named below, plus these, which postdate the sketch:
`manage_tenants.py`, `read_audit_log.py`, `read_usage_analytics.py`,
`pending_enrolment.py`, `recovery_codes.py` and `list_capabilities.py`, and the
`gateway_info.py`, `tenants.py`, `logs.py`, `usage.py` and `invitations.py`
routers. There is no `jobs.py`: download progress is
`GET /admin/models/download-jobs/{id}`, on the router that starts the download.
[security.md](./security.md) §13.0 remains the checked control-by-control state.

Present and not listed below: `app/shared/clock.py` (injected time, so expiry
behaviour is testable), `domain/entities/chat.py` (`Message`,
`CompletionChunk`), `domain/entities/capability.py` (`KNOWN_CAPABILITIES`, the
one definition of what a capability may be named — it lived in a use case and
two other places kept copies that had each drifted from it, see
[PROGRESS.md](../PROGRESS.md) 2026-07-28),
`domain/services/api_key_service.py`, and `adapters/persistence/mappers.py`.

```
backend/
  alembic/
    versions/
    env.py
  app/
    domain/
      entities/
        model.py                    # Model, ModelState
        node.py                     # Node, NodeStatus
        capability.py               # Capability
        routing_policy.py           # RoutingPolicy, RoutingCandidate, Requirement
        api_key.py                  # ApiKey
        user.py                     # User, Role
        invitation.py               # Invitation, RecoveryCode
        actor.py                    # Actor, Scope
        usage.py                    # UsageRecord
      services/
        routing_service.py          # Pure logic: capability + node state -> target model
        usage_service.py            # Usage accounting and quota checks
        memory_budget_service.py    # Refuses loads that would exceed node capacity
      ports/
        model_runtime_port.py
        model_repository_port.py
        node_repository_port.py
        routing_policy_repository_port.py
        api_key_repository_port.py
        user_repository_port.py
        invitation_repository_port.py
        usage_repository_port.py
        knowledge_repository_port.py     # Phase 2
        password_hasher_port.py          # argon2id lives in an adapter, not the domain
        totp_port.py
        authorization_port.py
        audit_port.py
        metrics_port.py                  # Phase 2
        cache_port.py
        job_progress_port.py             # Model download progress
      exceptions.py                 # DomainError hierarchy, see §5

    application/
      use_cases/
        route_chat_request.py
        register_model.py
        download_model.py
        load_model.py
        unload_model.py
        create_api_key.py
        revoke_api_key.py
        list_users.py
        set_user_role.py
        invite_user.py
        accept_invitation.py            # set password + enrol TOTP in one step
        authenticate_local.py           # password then TOTP, see §7
        change_password.py
        issue_password_reset.py
        bootstrap_first_admin.py
        get_dashboard_metrics.py
      dto.py

    adapters/
      runtime/
        ollama_adapter.py           # Implements ModelRuntimePort
        vllm_adapter.py             # Phase 2
        mlx_adapter.py              # Phase 2
        validation.py               # Model reference validation, see security.md §7.1
      persistence/
        sqlalchemy_models.py        # ORM models, deliberately separate from domain entities
        postgres_model_repository.py
        postgres_node_repository.py
        postgres_routing_policy_repository.py
        postgres_api_key_repository.py
        postgres_user_repository.py
        postgres_usage_repository.py
        qdrant_knowledge_repository.py   # Phase 2
      cache/
        redis_adapter.py
        redis_job_progress.py
      crypto/
        argon2_hasher.py            # Implements PasswordHasherPort
        pyotp_totp.py               # Implements TotpPort
      authz/
        role_authorization.py       # Implements AuthorizationPort
      audit/
        postgres_audit.py           # Implements AuditPort
      metrics/
        prometheus_adapter.py       # Phase 2
      http/
        egress_guard.py             # SSRF guard for outbound calls, see security.md §7.2

    interfaces/
      http/
        routers/
          chat.py                   # POST /v1/chat/completions,
                                    #  GET /v1/models                    (gateway)
          admin_chat.py             # POST /admin/chat                   (admin)
          gateway_info.py           # GET  /admin/gateway                (admin)
          models.py
          routing_policies.py
          api_keys.py
          nodes.py
          users.py                  # /admin/users, /admin/me
          auth.py                   # /admin/auth/{login,totp,logout,accept-invite,
                                    #   change-password}          (public entrance only)
          jobs.py                   # /admin/jobs/{id}
          dashboard.py
          health.py                 # /healthz, /readyz
        middleware/
          client_ip.py              # Trusted proxy resolution, see deployment.md §7
          geo_filter.py             # Country allowlist, see security.md §4.1
          tailnet_identity.py       # Tailscale header identity  (tailnet app only)
          session_auth.py           # Server-side session        (public app only)
          api_key_auth.py           # API key identity           (gateway only)
          csrf.py                   # Double-submit token        (public app only)
        schemas/
          chat_schemas.py
          model_schemas.py
          user_schemas.py
        errors.py                   # DomainError -> HTTP mapping, see §5
        dependencies.py

    infrastructure/
      config.py                     # Settings, env + Docker secrets
      db.py
      di.py                         # Composition root
      concurrency.py                # Global inference semaphore
      main_gateway.py               # Mounts /v1/* only
      main_admin_tailnet.py         # Mounts /admin/* with Tailscale identity
      main_admin_public.py          # Mounts /admin/* with session auth + CSRF

  tests/
    unit/                           # domain + application, fake adapters, no Docker
    integration/                    # real adapters, needs docker compose
```

Three ASGI applications exist rather than one, because the two admin entrances have different trust models and must be isolated by socket binding rather than by conditional logic. See [deployment.md](./deployment.md) §4.

## 3. Ports

Ports are `Protocol` classes, so adapters satisfy them structurally without inheritance.

```python
# domain/ports/model_runtime_port.py
from typing import Protocol, AsyncIterator
from app.domain.entities.chat import CompletionChunk

class ModelRuntimePort(Protocol):
    def generate(self, ref: str, messages: list[Message],
                 max_tokens: int | None = None,
                 thinking: bool = True) -> AsyncIterator[CompletionChunk]:
        """Stream completion chunks. Implementations are async generator functions.

        Declared with `def`, not `async def`: an async generator function is called
        without await and returns the iterator directly. Declaring it `async def`
        here would mean "await this to obtain an iterator", which no implementation
        actually does, and callers written against that signature crash at runtime.

        `thinking` is per call rather than adapter state: one resident copy of a
        model has to serve both kinds of request, because the registry cannot hold
        the same weights twice and the memory budget would double-count them if it
        could. `True` means "send nothing and let the model do what it does" — no
        runtime offers a way to ask for *more* deliberation.
        """

    async def load(self, ref: str) -> None: ...
    async def unload(self, ref: str) -> None: ...
    async def health(self) -> bool: ...
    def pull(self, ref: str) -> AsyncIterator[PullProgress]: ...
```

That docstring exists because the distinction is a common and silent error. `async def f() -> AsyncIterator[T]` with `yield` in the body *is* an async generator function, but the annotation then describes the call result, not something awaitable. A Protocol that writes `async def` invites callers to `await port.generate(...)`, which raises immediately.

Ports the domain defines, and what implements them:

| Port | Phase 1 adapter | Built |
|---|---|---|
| `ModelRuntimePort` | `OllamaAdapter` | yes |
| `ModelRepositoryPort`, `NodeRepositoryPort`, `RoutingPolicyRepositoryPort` | Postgres | yes |
| `ApiKeyRepositoryPort`, `UserRepositoryPort`, `InvitationRepositoryPort`, `UsageRepositoryPort` | Postgres | yes |
| `AuthorizationPort` | `RoleAuthorization` | yes |
| `CachePort` | `RedisCache`, `InMemoryCache` | yes |
| `PasswordHasherPort` | `Argon2Hasher` | **no adapter** |
| `TotpPort` | `PyotpTotp` | **no adapter** |
| `AuditPort` | `PostgresAudit` | **no adapter, no call sites** |
| `JobProgressPort` | Redis | **no adapter** |
| `KnowledgeRepositoryPort`, `MetricsPort` | Phase 2 | correctly absent |

A port with no adapter is not neutral: `AuditPort` and the `audit_log` table
both exist, which reads as an audit trail that is in fact never written.

## 4. Domain Services

`RoutingService` is the core of the platform and is pure logic with no I/O.

```python
# domain/services/routing_service.py
class RoutingService:
    def select(self, policy: RoutingPolicy, models: dict[str, Model],
               nodes: dict[str, Node]) -> Model:
        """Pick the highest-priority candidate whose requirements are satisfied."""
        for candidate in sorted(policy.candidates, key=lambda c: -c.priority):
            model = models.get(candidate.model_alias)
            if model is None:
                continue
            node = nodes.get(model.node_id)
            if node is None:
                continue
            if self._satisfies(candidate.require, model, node):
                return model
        raise NoAvailableModelError(policy.capability)

    def _satisfies(self, req: Requirement, model: Model, node: Node) -> bool:
        # Structured field comparison only. See the prohibition below.
        if req.node_status and node.status not in req.node_status:
            return False
        if req.model_state and model.state not in req.model_state:
            return False
        return True
```

**Requirements are never evaluated as expressions.** No `eval`, no `exec`, no expression-evaluator library, no template engine. Routing policies are editable through the admin UI and evaluated inside the gateway process, so an expression evaluator would turn policy editing into remote code execution. `Requirement` is a closed dataclass; adding a new condition means adding a field and a comparison, which is a code change subject to review.

## 5. Error Handling

All domain errors derive from a single base carrying a stable machine code and a message that is safe to return to a caller.

```python
# domain/exceptions.py
class DomainError(Exception):
    code: str = "internal_error"
    public_message: str = "An internal error occurred."
```

A single exception handler registered in `interfaces/http/errors.py` performs the mapping. Routers do not write their own `try/except` blocks for domain errors.

| Exception | Status | Notes |
|---|---|---|
| `ModelNotFoundError` | 404 | |
| `NoAvailableModelError` | 503 | Never names the models that were considered |
| `ModelStateConflictError` | 409 | For example, unloading a model that is not loaded |
| `InsufficientMemoryError` | 409 | Returns required and available capacity |
| `ContextTooLongError` | 413 | Input ceiling, checked before any token is produced |
| `QuotaExceededError` | 429 | With `Retry-After` |
| `RateLimitedError` | 429 | With `Retry-After` |
| `CountryNotAllowedError` | 403 | Generic body, does not echo the detected country |
| `UntrustedProxyError` | 400 | Logged at warning level, indicates misconfiguration or spoofing |
| `InvalidNodeAddressError` | 400 | |
| `NotAuthenticatedError` | 401 | |
| `NotAuthorizedError` | 403 | Does not reveal whether the target resource exists |
| `InvalidModelReferenceError` | 400 | |
| `InvalidCredentialsError` | 401 | **Identical body for unknown login and wrong password**, see §7 |
| `TotpRequiredError` | 401 | Password accepted, second factor outstanding |
| `InvalidTotpError` | 401 | Also raised on replay of an already-used counter |
| `InvitationInvalidError` | 400 | Covers unknown, expired, and already-consumed tokens alike |
| `WeakPasswordError` | 400 | Returns the reason so the UI can guide the user |

Two response shapes exist. The gateway follows the OpenAI error envelope so that existing clients parse it:

```json
{ "error": { "type": "service_unavailable", "code": "no_available_model", "message": "..." } }
```

The admin API uses a plainer shape:

```json
{ "code": "insufficient_memory", "message": "...", "details": { "required_gb": 24, "available_gb": 12 } }
```

`public_message` is the only text that crosses the boundary. As required by [security.md](./security.md) §4.4, error bodies never contain internal model names, node addresses, or stack traces. The full exception is written to the application log with the request ID so that an operator can correlate.

**There is a third shape, and it is not ours.** `install_error_handlers` registers a handler for `DomainError` and nothing else, so a request the schema rejects never reaches it: FastAPI answers 422 with its own `{"detail": [...]}`. That is a reasonable place to stop — the body is about the request's structure, not about the platform, and it leaks nothing. But it means "every error carries `code`" is false, and a client written to that rule throws on the one failure it is most likely to hit while being written. The public API page documents the exception explicitly for that reason; anything else claiming the envelope is universal is wrong.

**Two statuses carry two codes each, which is why clients must branch on the code.** 403 is both `not_authorized` (the key is valid but was not issued for this capability) and `country_not_allowed` (the geo filter, §4.1a); 429 is both `rate_limited` (retry, `Retry-After` is set) and `quota_exceeded` (retrying inside the same day cannot succeed). Treating either pair as one condition produces a client that retries forever or reissues keys forever.

## 6. The Streaming Contract

Streaming crosses every layer, and most of the subtle failure modes in this system live here. The rules are fixed rather than left to each implementation.

**What flows through the port.** The domain emits `CompletionChunk`, a dataclass with a text delta, an optional finish reason, optional usage counts, and a separate `reasoning` string. It never emits SSE-formatted strings. Wire framing is an interface-layer concern, which is what lets the same use case serve the OpenAI-compatible gateway endpoint and the admin chat endpoint.

**Reasoning is a distinct field, on the port and on the wire.** A thinking model leaves its answer empty and fills a reasoning channel until it is done, which for a hard question can be the entire generation. Two rules follow, and both are load-bearing:

- It is never merged into `delta`. A client concatenating `content` into the reply would put the model's scratch work into the answer and then send it back as history on the next turn.
- It is never dropped either. A chunk carrying only reasoning still has to be framed, because a stream that emits nothing while the model thinks is a silent socket, and any intermediary with an idle timeout will cut it. This is not hypothetical: it cut a 93-second generation at exactly 30 seconds and surfaced to the browser as a 500 with no trace in the backend log.

On the wire this is the `reasoning_content` key inside `choices[].delta`, alongside `content` and never in place of it, and a field of the same name on the non-streaming `CompletionMessage`. The spelling matches what DeepSeek and vLLM already emit; an OpenAI client that does not know the key ignores an unrecognised delta field, which is the correct outcome for one.

**`think` is a request field, and what a caller sends is not what the runtime receives.** It is an extension to the OpenAI request schema — there is no standard field for this, and the alternative is a caller with no way to reach the behaviour at all. Omitted takes the deployment default (`OLLAMA_THINKING`).

Three properties, each of which was arrived at by measurement rather than preference:

- **`true` is never sent onward.** Ollama rejects `think: true` for a model that does not support thinking, failing the request outright, so a registry holding both kinds cannot ask for thinking globally. The adapter therefore maps `thinking=True` to sending *no* `think` field — "leave the model alone". That asymmetry is what makes `think: true` safe for a caller to send, and callers do send it: a client that omitted the field when it wanted thinking could not override a deployment whose default was `false`, and a UI built that way displayed the opposite of what it did.
- **There is no middle setting.** Ollama accepts `think: "low"` for a model that supports graded thinking and the behaviour is measurably identical to the default, so the graded values are deliberately not offered rather than passed through as a promise nothing keeps.
- **It is per request, not per model, and cannot be otherwise.** `ix_models_node_ref` is unique on `(node_id, runtime, ref)`, so the same weights cannot be registered twice under two aliases; and if they could, `MemoryBudgetService` sums `memory_gb` over every loaded row and would see double what is resident, refusing the second load. One resident copy has to serve both kinds of request, so the decision travels with the request and the port takes it as an argument rather than holding it as adapter state.

Unlike `max_tokens` it is not clamped. A caller asking a deliberating model to answer directly is asking for less hardware work, not more, so there is nothing to protect against.

**Where framing happens.** `interfaces/http/routers/chat.py` converts chunks into `data: {...}\n\n` frames and terminates with `data: [DONE]`. `admin_chat.py` may use a simpler frame shape.

**Non-streaming requests.** The port only offers a streaming interface. When a client sends `stream: false`, the router consumes the iterator to exhaustion and assembles a single response. There is exactly one execution path, which avoids the two implementations drifting apart.

**Concurrency slot lifetime.** The global inference semaphore is held for the whole generator lifetime, not just the call that creates it.

```python
# application/use_cases/route_chat_request.py
class RouteChatRequest:
    async def execute(self, actor: Actor, capability: str,
                      messages: list[Message], max_tokens: int | None = None,
                      thinking: bool | None = None) -> AsyncIterator[CompletionChunk]:
        policy = await self._policies.get(capability)
        target = self._routing.select(policy, *await self._current_state())
        runtime = self._runtimes[target.runtime]

        produced = 0
        async with self._concurrency.slot():         # released in finally, below
            try:
                # `thinking=None` defers to the deployment default, which this
                # use case owns so no adapter holds a second copy of it.
                async for chunk in runtime.generate(target.ref, messages, ceiling,
                                                    thinking):
                    produced += chunk.token_count
                    yield chunk
            finally:
                # Runs on normal completion, on client disconnect, and on error.
                await self._usage.record(actor, target, produced)
```

**Callers must close the generator deterministically.** A `finally` inside an async generator runs when the generator is closed, which is not guaranteed to be prompt if a consumer simply abandons it. Every consumer wraps iteration in `contextlib.aclosing()`, so a slot is never leaked when a client disconnects mid-stream:

```python
async with aclosing(use_case.execute(actor, capability, messages)) as stream:
    async for chunk in stream:
        yield frame(chunk)
```

**Client disconnect.** Starlette throws `CancelledError` into the generator when the client goes away. Adapters must therefore close their upstream HTTP stream in a `finally` block, otherwise the runtime keeps generating tokens for nobody. This is the guardrail that [security.md](./security.md) §4.3 requires; it only works if every layer propagates cancellation instead of swallowing it.

**Usage accounting on partial output.** Token counts are only known as generation proceeds. Usage is recorded in the `finally` block, so a stream that ends early still bills what was produced. Quota checks happen before generation starts, which means a single request can overshoot a quota by at most one request; that is accepted rather than solved with mid-stream aborts.

**Errors after the first byte.** Once the response has started, the status code cannot be changed. An error mid-stream emits a terminal error frame and closes the connection. Clients that only read the HTTP status will see 200 with a truncated body, which is inherent to SSE and is documented for API consumers rather than worked around.

## 7. Authentication and Authorization

**Authentication** produces an `Actor` and happens in `interfaces/http/middleware`, with a different middleware per application:

| Application | Middleware | Identity source |
|---|---|---|
| `main_gateway` | `api_key_auth` | `Authorization: Bearer nx_live_...` |
| `main_admin_tailnet` | `tailnet_identity` | `Tailscale-User-Login` header |
| `main_admin_public` | `session_auth` + `csrf` | Server-side session cookie, established by password plus TOTP |

`AuthenticateLocal` is a use case rather than middleware logic, because it carries real business rules: password verification, then TOTP verification against a stored counter, then session issue. Two constraints are structural rather than incidental and belong in the use case where they can be unit tested:

- **An unknown login must cost the same as a wrong password.** The use case runs a dummy hash verification when no user matches, so neither the response nor the timing distinguishes the two cases.
- **A TOTP counter is accepted once.** The last accepted counter is persisted and any code at or below it is rejected, which is what stops a code observed in a phishing proxy from being reused inside its window.

**Authorization** happens in `application/use_cases`, which is the right altitude for it:

- Not in `domain`: pure business logic should not know who is calling.
- Not in routers: a use case reachable from more than one entrance would need the check duplicated, and one of them will eventually be forgotten.

```python
# application/use_cases/load_model.py
class LoadModel:
    required_scope = Scope.MODEL_WRITE

    async def execute(self, actor: Actor, model_id: ModelId) -> None:
        self._authz.require(actor, self.required_scope)
        ...
        await self._audit.record(actor, "model.load", target=model_id)
```

`AuthorizationPort` and `AuditPort` are both domain ports. Making them ports rather than helper functions means "every administrative action is authorized and audited" is enforced by the shape of the code rather than by remembering.

## 8. Configuration and Secrets

`infrastructure/config.py` uses pydantic-settings reading both environment variables and mounted secret files.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        secrets_dir="/run/secrets",   # Docker secrets take precedence over env
    )
```

Non-secret configuration comes from environment variables; secrets (database password, API key pepper, TOTP encryption key, session signing key) are mounted as files. Environment variables appear in `docker inspect` output and in the process list, so anyone able to run commands on the host can read them. The full variable list lives in [deployment.md](./deployment.md) §10.

## 9. Health Endpoints

Both `/healthz` and `/readyz` are mounted on every application, and both bypass the geo filter, trusted-proxy check, and authentication. Without that exemption the reverse proxy cannot probe the service at all.

| Endpoint | Checks | Response |
|---|---|---|
| `GET /healthz` | Nothing. The process is running | `200 {"status":"ok"}` |
| `GET /readyz` | Database, cache, and for the gateway the runtime, concurrently and each bounded by a timeout | `200` or `503` with per-dependency booleans |

`/readyz` returned hardcoded booleans for a while and could never produce a
503, so anything gating a rollout on it was gating on a constant. The timeout
matters for the same reason: a probe that hangs is worse than one that fails,
because the orchestrator waits instead of acting.

Neither response includes a version string, model list, or hostname. `/readyz` reveals which dependencies are down, which is mildly useful to an attacker, so on the gateway it is published only on the tailnet-bound port.

## 10. Local Development Mode

The development machine is Windows. It has no `tailscale serve`, no openresty, and no GeoLite2 database. Taken literally, the middleware described above rejects every request, so the application would be unrunnable locally. The local credential flow itself depends on nothing external and does run locally under `AUTH_MODE=local`.

`AUTH_MODE=dev` disables the trusted-proxy check and resolves the caller to the peer address, which is what lets the stack run without a proxy in front of it. It is read in exactly one place, `middleware/client_ip.py`.

It does **not** inject a fixed admin `Actor`, contrary to an earlier version of this paragraph; there is no such injection anywhere, and the gateway still requires a real API key in development. That will need building alongside the admin entrances, and the fail-fast below is what keeps it from mattering in production.

**This is a production-fatal setting.** `infrastructure/config.py` fails fast at startup if `AUTH_MODE=dev` and `ENV=production` are both set. The check is a startup assertion rather than a runtime branch, so a misconfigured deployment refuses to boot instead of silently serving an open admin API. [security.md](./security.md) §14 carries a matching pre-launch check.

## 11. Migrations

Alembic. Phase 1 creates `nodes`, `models`, `routing_policies`, `api_keys`, `users`, `invitations`, `recovery_codes`, `usage_records`, and `audit_log`.

Migrations run as a **one-shot Compose service** that the application services depend on with `condition: service_completed_successfully`. They are not run from an application entrypoint, because three containers start from the same image and would race each other.

## 12. Testing

- **Unit**: `domain/services` and `application/use_cases` with fake adapters. `FakeModelRuntimePort` yields a fixed sequence of chunks, which makes the streaming contract in §6 testable without a runtime. These run in milliseconds and need no Docker.
- **Integration**: `adapters/persistence` and `adapters/runtime` against real dependencies started by Compose.

Cases worth pinning down early because they are easy to get wrong and expensive to discover late: client disconnect releases the concurrency slot; a mid-stream error produces a terminal frame; `AUTH_MODE=dev` under `ENV=production` refuses to start; the public application strips `Tailscale-*` headers; an unknown login and a wrong password are indistinguishable; a replayed TOTP counter is rejected; a consumed invitation token cannot be reused.
