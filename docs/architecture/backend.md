# Backend Architecture: Hexagonal (Ports and Adapters)

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md). Defines the internal layering of the FastAPI project.

## 1. Why Hexagonal

The requirement itself demands dependency inversion: runtimes must be swappable without touching the API or agent layers. Hexagonal architecture turns that sentence into a structural rule rather than a matter of developer discipline.

- `domain` knows nothing about FastAPI, SQLAlchemy, or Ollama. It only knows the ports it defines.
- `adapters` implement those ports and handle all contact with the outside world.
- Dependencies always point inward: `interfaces -> application -> domain`. Adapters implement `domain.ports`, but `domain` never imports adapters.

A concrete payoff specific to this project: the gateway and the two admin entrances are three separate containers that share the entire `domain/` and `application/` layers. Only the mounted routers differ. Splitting them for security reasons (see [security.md](./security.md) §1) costs no duplicated code.

## 2. Folder Structure

**This is the current layout.** The 2026-08-20 separation pass replaced the
former repository, ORM, mapper, schema, dependency-wiring, orchestration and
adapter mega-files with bounded-context packages. Their `__init__.py` modules
are explicit compatibility façades: existing imports still resolve to the same
objects, while implementation dependencies point at the focused modules.

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
`pending_enrolment.py`, `recovery_codes.py`, `list_capabilities.py`,
`manage_knowledge.py`, `ingest_document.py`, `search_knowledge.py`,
`embed_texts.py`, `ground_chat.py`, `manage_prompt_templates.py`,
`apply_prompt_template.py`, `assist_operator.py`, `manage_retention.py`,
`read_prompt_logs.py`, `read_refusals.py`, `read_host_status.py`,
`manage_own_account.py` and `manage_evaluations.py`, and the
`gateway_info.py`, `tenants.py`, `logs.py`, `usage.py`, `invitations.py`,
`responses.py`, `knowledge.py`, `prompt_templates.py`, `assistant.py`,
`retention.py`, `prompt_logs.py`, `refusals.py`, `host.py`, `me.py`,
`roles.py`, `metrics.py` and `evaluations.py` routers — twenty-seven router
modules and thirty-two use cases in all, counted 2026-08-18. There is no `jobs.py`: download progress is
`GET /admin/download-jobs/{job_id}`, on the router that starts the download.
[security.md](./security.md) §13.0 remains the checked control-by-control state.

Present and not listed below: `app/shared/clock.py` (injected time, so expiry
behaviour is testable), `domain/entities/chat.py` (`Message`,
`CompletionChunk`), `domain/entities/capability.py` (`ISSUABLE_CAPABILITIES`
and `ROUTABLE_CAPABILITIES`, the one definition of what a capability may be
named — it lived in a use case and two other places kept copies that had each
drifted from it, see [PROGRESS.md](../PROGRESS.md) 2026-07-28, and it became two
sets on 2026-07-29 so that every reader has to say whether it means "may be
issued for" or "may be routed to"; [security.md](./security.md) §7.5.1),
`domain/services/api_key_service.py`, and the focused packages summarized here:

```
domain/{entities/actor,entities/evaluation,exceptions,ports/repositories}/
  # catalogs/entities, scoring, contextual errors, and repository protocols
application/use_cases/
  route_chat_request/          # estimates, guardrails, diagnostics, session, finalization
  manage_{models,api_keys,knowledge}/
  ingest_document/ authenticate_local/ assist_operator/
adapters/
  persistence/{sqlalchemy_models,mappers,repositories}/
  runtime/{ollama_adapter,mlx_adapter}/
  tokenizer/gguf_token_counter/
interfaces/http/
  errors/ sse/ responses_sse/ assistant_proposal/
  middleware/api_key_auth/
  routers/{chat,responses,knowledge}/
  schemas/admin_schemas/
infrastructure/{config,di,import_evaluation}/
```

Each line above is a package with named modules for its data-flow stages or
bounded contexts. The compact layer overview below remains intentionally
non-exhaustive; the package map above is authoritative for decomposed areas.

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
        actor/                      # Role, Scope, catalogs, Actor capability behavior
        usage.py                    # UsageRecord
        refusal.py                  # Refusal: the stored copy of what a caller was told
        evaluation/                 # entities/value objects and aggregation/scoring
      services/
        routing_service.py          # Pure logic: capability + node state -> target model
        debug_window.py             # The one ceiling on the debug-logging window,
                                    #   shared by both credential kinds
        memory_budget_service.py    # Refuses loads that would exceed node capacity
      ports/
        repositories/               # platform, identity, observability, knowledge,
                                    #   retention/templates and evaluations
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
      exceptions/                   # contextual DomainError families, see §5

    application/
      use_cases/
        route_chat_request/         # thin orchestrator plus ordered pipeline stages
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
        authenticate_local/          # coordination, password, TOTP, recovery, results
        change_password.py
        issue_password_reset.py
        bootstrap_first_admin.py
        get_dashboard_metrics.py
      dto.py

    adapters/
      runtime/
        ollama_adapter/             # encoding, decoding, generation and lifecycle
        vllm_adapter.py             # Phase 2
        mlx_adapter/                # translation, generation, lifecycle and integrity
        validation.py               # Model reference validation, see security.md §7.1
      tokenizer/
        gguf.py                     # Reads a GGUF's metadata header, nothing else
        ollama_blobs.py             # `ref` -> manifest -> the weights file it resolves to
        gguf_token_counter/         # construction, templates, cache and adapter
      persistence/
        sqlalchemy_models/          # Base plus five bounded-context row modules
        mappers/                    # no dependency on repository implementations
        repositories/               # shared tenant scope plus contextual repositories
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
          chat/                     # translation, collection, route
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
          knowledge/                # collections, documents/jobs, search
          responses/                # translation, tools, collection, route
          dashboard.py
          health.py                 # /healthz, /readyz
        middleware/
          client_ip.py              # Trusted proxy resolution, see deployment.md §7
          geo_filter.py             # Country allowlist, see security.md §4.1
          tailnet_identity.py       # Tailscale header identity  (tailnet app only)
          session_auth.py           # Server-side session        (public app only)
          api_key_auth/             # resolution, enforcement, Actor construction
          csrf.py                   # Double-submit token        (public app only)
        schemas/
          chat_schemas.py
          admin_schemas/            # ten HTTP/domain surfaces, stable component names
        errors/                     # mapping, details, persistence and handlers
        dependencies.py

    infrastructure/
      config/                       # flat settings, derived values and validation
      db.py
      di/                           # stable dependency identities, contextual providers
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
| `PasswordHasherPort` | `Argon2Hasher` | yes |
| `TotpPort` | `PyotpTotp` | yes |
| `AuditPort` | `PostgresAudit` | yes; fifty call sites across eighteen use cases |
| `JobProgressPort` | `CacheJobProgress`, over Redis | yes |
| `KnowledgeRepositoryPort` | `PostgresKnowledgeRepository` | yes, built 2026-07-30 |
| `EvaluationRepositoryPort` | `PostgresEvaluationRepository` | yes, built 2026-08-17 |
| `RefusalWriterPort`, `RefusalRepositoryPort` | `PostgresRefusalWriter`, `PostgresRefusalRepository` | yes, built 2026-08-18. Two ports rather than one: the gateway holds only the writer, so it records what it refused without being able to read any of it back — the same split `db_roles.py` enforces at the database |
| `MetricsPort` | Phase 2 | correctly absent; the memory budget still uses static node capacity |
| `TokenCounterPort` | `GgufTokenCounter` | yes |

**This table said "no adapter" for the four rows above `MetricsPort` until
2026-08-18, and the conclusion drawn from it was the opposite of the truth.**
The paragraph here read "`AuditPort` and the `audit_log` table both exist,
which reads as an audit trail that is in fact never written". Every one of the
four was wired in `di.py`, and the audit trail in particular is written from
fifty call sites; the sentence survived because it was checked against the
table above it rather than against `di.py`. The observation it was making is
still worth keeping in the abstract — a port with no adapter is not neutral,
because the table and the schema together read as a control that exists — but
it is not a statement about this platform, and a status column that is only
ever written once is worse than none (the same defect [ARCHITECTURE.md](../ARCHITECTURE.md) §3 records
about its own Built column).

**Every domain error is stored where its caller can read it (§9.5).** The shared
exception handler writes a `refusals` row carrying the code, the status, the
public message and the caller-facing figures — built by the same function that
builds the response body, so a stored refusal cannot disagree with the one that
was sent. The handler is the write point rather than any use case because it is
the only place every `DomainError` passes through: the refusal that motivated
the table was an API key's expiry on the admin surface, which reaches no
inference code at all.

**`TokenCounterPort` is the one port that may answer "I cannot say".** It counts
a prompt with the vocabulary and chat template read out of the GGUF the target's
`ref` resolves to, and returns `None` for a target this host holds no weights
for — an MLX model, a reference not yet pulled, a deployment that mounts no
model store. `RouteChatRequest` falls back to the character estimate there and
logs which reference it happened for, because the guardrail it feeds runs before
any hardware is committed and "no counter, no ceiling" is not an available
state. It is also the only port whose adapter reads a file the platform does not
own: the mount is read-only, and nothing past the metadata header is ever read.

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
| `ContextTooLongError` | 413 | Input ceiling, checked before any token is produced. Carries `estimated`, `limit`, `composition` and `basis` |
| `ApiKeyLifetimeError` | 409 | Carries `maximum_days`, the policy the expiry exceeded |
| `CapabilityNotIssuedError` | 403 | Carries `capability` and `available`, both of which the caller already holds |
| `QuotaExceededError` | 429 | With `Retry-After` |
| `RateLimitedError` | 429 | With `Retry-After` |
| `CountryNotAllowedError` | 403 | Generic body, does not echo the detected country |
| `UntrustedProxyError` | 400 | Logged at warning level, indicates misconfiguration or spoofing |
| `InvalidNodeAddressError` | 400 | |
| `NotAuthenticatedError` | 401 | |
| `NotAuthorizedError` | 403 | Does not reveal whether the target resource exists |
| `InvalidModelReferenceError` | 400 | |
| `ModelIntegrityError` | 502 | Downloaded weights disagree with the digest the repository states. 502 because the party that failed is upstream, and the message does not say "retry": a corrupted transfer would succeed on a second attempt and a repository whose bytes disagree with its own metadata never will, and this error cannot tell them apart |
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

**Two statuses carry several codes each, which is why clients must branch on the code.** 403 is `capability_not_issued` (the `model` field named a capability this key may not call — the message names the ones it may), `not_authorized` (the key may not perform the action at all) and `country_not_allowed` (the geo filter, §4.1a); 429 is both `rate_limited` (retry, `Retry-After` is set) and `quota_exceeded` (retrying cannot succeed until spend ages out of the window). Treating any of these as one condition produces a client that retries forever or reissues keys forever.

**Telling a client to branch on the code was never enough, because no client library reads it.** OpenAI's do their branching on `type`, and `type` came from the status alone until 2026-08-14 — so a spent quota introduced itself as `rate_limit_error`, the one classification that asks for the retry it cannot satisfy. `OPENAI_ERROR_TYPE_OVERRIDES` now maps `quota_exceeded` to `insufficient_quota`, walked over the MRO like the status map beside it. The failure this closes was reported as `exceeded retry limit, last status: 429` by a Codex session that had done exactly what the envelope told it to.

**`quota_tokens_per_day` measures a rolling 24 hours, not a calendar day.** It does not reset at midnight and it does not clear all at once: each past request stops counting 24 hours after it was made, so an exhausted key recovers in pieces. `Retry-After` was a fixed `3600` regardless — a figure that matched the truth only by accident, and sent callers back up to twenty-three hours early. The middleware now projects the real moment from the same rows the quota is summed from (`PostgresUsageRepository.quota_recovers_at`), the header carries it, and the public message states it in round units. Where the projection cannot be made the header is omitted rather than guessed.

**The quota gates inference, not metadata.** `GET /v1/models` authenticates through `authenticate_api_key_without_quota`, which keeps every check that protects the platform — validity, expiry, rate limit, CIDR, country — and drops the one budget the call cannot spend. It runs no model. While it was gated, an exhausted quota stopped OpenAI-compatible agents at startup, since they all list models before their first request, and the operator saw a client that would not connect rather than a key that had run out.

`capability_not_issued` split off from `not_authorized` on 2026-08-14, on the rule the `no_available_model` split follows: a separate remedy earns a separate code. It is also the one refusal here that names what it refused, which it can afford because the capability came from the caller and the list is what `GET /v1/models` already returns them.

**A key may opt out of that refusal, and nothing else may.** `api_keys.default_capability` names what to serve when a request asks for a capability the key does not hold; null, the default, refuses as before. The pressure to make this deployment-wide is real — `model` taking a capability rather than a model name is its one true divergence, Codex's picker overrides a configured `model` line and sends its own slugs, and three integrations have lost time to it — and it is refused for one reason: the refusal is the only channel that tells an integrator their client overrode them, so a platform-wide fallback would buy convenience by making that misconfiguration permanent and invisible. Per key, it is the issuer's stated choice, visible in the key's settings, audited when set, and withdrawable.

Three properties keep it honest. It is **a substitution, never a widening** — the value must already be in `scopes`, checked at issue, at edit, and once more in `Actor.capability_for`, which re-derives rather than trusts, so a row written by another hand still reaches nothing new. It is **announced**, in `X-Capability-Defaulted` on the response, the same channel and the same rule as `X-Dropped-Tools`. And it is **recorded**: `usage_records.requested_capability` keeps what the caller actually sent, null when the two agree, because turning the setting on removes the refusal and the evidence has to outlive both a header the client may not read and a log line that rotates. The response body still echoes `model` as it arrived.

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

**The default is resolved in three levels, and the middle one is per capability.** A request that sets `think` wins; otherwise the routing policy's `thinking` column decides; otherwise `OLLAMA_THINKING` does. The policy level was added on 2026-08-05 with tool calling, because that is the level at which the answer actually differs: `chat` wants a model to deliberate, `assist` cannot afford it beside a settings form, and an agent client on `code` pays the cost again on *every tool round trip* — a ten-step task deliberating ten times over. The column is nullable, and null means "no opinion, take the deployment default", which is what every policy written before it existed means. Only the request may be `False` meaningfully, so both levels test `is None` rather than truthiness.

**Tool calling.** `CompletionChunk` carries whole `ToolCall` values, never fragments, and `Message` carries `tool_calls`, `tool_call_id` and `name` so a tool result can be replayed. Four decisions here are not obvious and each was reached by asking what breaks *silently*:

- **`finish_reason` is rewritten to `tool_calls` in the adapter.** Ollama ends a generation that produced tool calls with `done_reason: stop`, which is true of the model and wrong for the client: an agent loop branches on this field alone to decide whether to execute a call. Told "stop" it treats the turn as finished, the calls are never run, and the conversation stalls with the model waiting on results nobody will produce.
- **The call id is minted by the adapter.** Ollama gives a call no id, and OpenAI requires one — it is the handle a client uses to pair its result back. It must be unique within a conversation rather than within a chunk, so an index would collide across turns and pair a result with the wrong call.
- **`arguments` stays JSON *text* through the domain.** It is model output and can be malformed, so the caller that has to recover needs the bytes the model produced rather than this platform's re-encoding of a parse that may have succeeded by accident. Runtimes that hand back a decoded object are re-encoded at the adapter boundary; a replayed conversation whose model once emitted invalid JSON is passed through rather than refused, or it would be impossible to continue.
- **A `tool_choice` the runtime cannot enforce is refused, not downgraded.** `none` is exact everywhere (the tools are simply withheld) and `auto` is the default. `required` and naming a function ask the runtime to constrain decoding, which neither runtime here exposes; a caller quietly served `auto` receives prose where their parser expects a call, and finds out somewhere far from the request. This is the same judgement the MLX adapter makes on `embed` and `unload`.

The wire framing question these raise is order. A runtime reports the call and the end of the turn in one event, so the `delta.tool_calls` frame must precede the terminal frame — a client that has seen `finish_reason` has stopped reading deltas for that choice. That is the same rule as the trailer below, arrived at from the other direction, and it is pinned by a test asserting on frame order.

Tool definitions and replayed calls count towards the context ceiling. They are prompt the model reads like any other, and they are the part an agent client grows without bound: leaving them out would let a caller carry an arbitrary payload past the guardrail in `tools`, which is the one field of an agent request that no person ever types.

**Where framing happens.** `interfaces/http/routers/chat.py` converts chunks into `data: {...}\n\n` frames and terminates with `data: [DONE]`. `admin_chat.py` may use a simpler frame shape.

**Trailers.** A stream may carry one final frame after the answer and before `[DONE]`, for something that could only be known once the whole answer existed. `/admin/assistant` uses it for a structured proposal it has to finish writing before it can be validated ([security.md](./security.md) §7.5). It is an optional argument to `sse.streaming_response`, not a second framing function, so there stays one implementation of the envelope, the error branch and the sentinel. Two orderings make it safe and both are pinned by tests: it precedes `[DONE]`, because a client is right to stop reading at the sentinel; and a stream that failed carries none, for the same reason `[DONE]` is withheld on error — whatever it described came from an answer that never finished.

The client half has a matching rule. `readChatStream` returns as soon as it sees a `finish_reason`, which is correct for a chat turn and would miss a trailer entirely, so a caller that expects one opts in and the reader continues to the sentinel. The frame is handed over undecoded: the shared frame schema strips unknown keys rather than rejecting them, so routing a trailer through it would deliver an empty object.

**Nothing may follow the terminal frame except a trailer, and the trailer is the only reason that rule needs stating.** A client is entitled to stop reading at `finish_reason`, so anything emitted afterwards is written to nobody. This has now been got wrong twice, in different code, for the same reason both times: *the frame that ends a stream is not the last one the code writes.* `RouteChatRequest` emitted a second terminal chunk at the token ceiling (2026-07-27), and `ProposalCollector` flushed its held-back text in the block after its loop, which runs after the terminal chunk has already been framed — costing every answer its last nine characters on any client that did not opt into the trailer (2026-07-29). Anything that buffers output must therefore release it **on** the chunk carrying the finish reason, not after iteration ends. Both cases are pinned by tests that assert on frame *order*, which is what neither of them had.

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
| `main_admin_tailnet` | `identity.resolve_tailnet_actor` | `Tailscale-User-Login` header |
| `main_admin_public` | `identity.resolve_session_actor` + `csrf` | Server-side session cookie, established by password plus TOTP |

The two resolvers share one file, `middleware/identity.py`, rather than the
`tailnet_identity.py` and `session_auth.py` this table named until 2026-08-18.
They are together because the half that is easy to get wrong is the part they
have in common: both end at `_actor_for`, which is the single place a `User`
row becomes an `Actor` with its role, tenant and scopes, and two files would
mean two copies of that.

**"Middleware" is the directory, not the ASGI stack, and the difference cost something.** `api_key_auth` and the admin identity resolvers are FastAPI *dependencies* — `Depends(...)` on a router — while `csrf`, the geo filter and header stripping are true stack-level middleware. FastAPI reads and JSON-parses the request body **before** it resolves dependencies (`fastapi/routing.py::get_request_handler`), so everything in the first group runs after the whole body is in memory. That was invisible until an unauthenticated 200 MiB request was answered with a parse error rather than a 401 (see [PROGRESS.md](../PROGRESS.md) 2026-08-07). The consequence for anything added here: a check that must run *before* the body is read cannot be a dependency, whichever directory it lives in. `middleware/body_limit.py` is the one that has to be, and it is stack-level for that reason alone.

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

`AUTH_MODE=dev` disables the trusted-proxy check and resolves the caller to the peer address, which is what lets the stack run without a proxy in front of it. This paragraph said it was read in exactly one place, `middleware/client_ip.py`; it is read in six, which is worth stating because "one place" is what makes a setting look safe to change. They are `config.py` (the production fail-fast below), `middleware/client_ip.py`, `middleware/identity.py` twice — it substitutes `DEV_TAILNET_LOGIN` for the absent Tailscale header, and stamps the resulting actor's `source` as `dev` rather than `tailnet` — and the two admin composition roots, which pass it to the geo filter and to the error handlers so a 401 body can tell the browser whether to reconnect to the tailnet or show a login form.

It does **not** inject a fixed admin `Actor`, contrary to an earlier version of this paragraph; there is no such injection anywhere, and the gateway still requires a real API key in development. That will need building alongside the admin entrances, and the fail-fast below is what keeps it from mattering in production.

**This is a production-fatal setting.** `infrastructure/config.py` fails fast at startup if `AUTH_MODE=dev` and `ENV=production` are both set. The check is a startup assertion rather than a runtime branch, so a misconfigured deployment refuses to boot instead of silently serving an open admin API. [security.md](./security.md) §14 carries a matching pre-launch check.

## 11. Migrations

Alembic. Phase 1 creates `nodes`, `models`, `routing_policies`, `api_keys`, `users`, `invitations`, `recovery_codes`, `usage_records`, and `audit_log`. Phase 2 has added, in migration order, `tenants` (`d4e8f1a2b6c9`), `knowledge_collections` and `knowledge_documents` (`e5f2c8d71a43`), `retention_policies` (`a1b2c3d4e5f6`), `prompt_templates` (`c2f7b90e4a15`), `prompt_logs` (`a1d6e93c7f52`), the three evaluation tables `evaluation_runs`, `evaluation_model_scores` and `evaluation_task_scores` (`d3f5b81a04c7`), and `refusals` (`e7b41c9d0a26`, with `f3c8a15d27be` adding the denormalised actor display) — nineteen tables across sixteen migrations, counted 2026-08-18, head `a4c1e07f2b9d`.

Migrations run as a **one-shot Compose service** that the application services depend on with `condition: service_completed_successfully`. They are not run from an application entrypoint, because five containers start from the same image — the gateway, the two admin entrances, `parser` and the migration job itself — and the three that open the database would race each other.

## 12. Testing

- **Unit**: `domain/services` and `application/use_cases` with fake adapters. `FakeRuntime` (`tests/unit/streaming_contract_fixtures.py`) yields a fixed sequence of chunks and records whether it was closed early, which makes the streaming contract in §6 testable without a runtime; scenario modules divide lifecycle, context guardrails, diagnostics and exact counting. A second `FakeRuntime` in `tests/unit/fakes.py` covers the registry use cases. These run in milliseconds and need no Docker.
- **Integration**: `adapters/persistence` and `adapters/runtime` against real dependencies started by Compose.

Cases worth pinning down early because they are easy to get wrong and expensive to discover late: client disconnect releases the concurrency slot; a mid-stream error produces a terminal frame; `AUTH_MODE=dev` under `ENV=production` refuses to start; the public application strips `Tailscale-*` headers; an unknown login and a wrong password are indistinguishable; a replayed TOTP counter is rejected; a consumed invitation token cannot be reused.
