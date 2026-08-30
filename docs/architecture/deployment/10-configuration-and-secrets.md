# 10. Configuration and Secrets

[← Deployment Architecture](../deployment.md)

Non-secret values are environment variables; secrets are mounted files read through `secrets_dir` ([backend.md](../backend.md) §8).

**Environment**

| Variable | Example | Notes |
|---|---|---|
| `ENV` | `production` | `development` locally |
| `AUTH_MODE` | `tailnet` / `local` / `dev` | `dev` refuses to start when `ENV=production`. Read in six places, not one; see [backend.md](../backend.md) §10 |
| `LOG_LEVEL` | `INFO` | This application's own `app.*` loggers, deliberately not the root, so raising it does not add a line per httpx call to the runtime. The lines below WARNING are the ones that say *why* a request was refused — `perimeter_rejected` is the only place the three causes of a 400 `untrusted_proxy` are distinguished, and the response distinguishes none of them |
| `DEV_TAILNET_LOGIN` | `dev@localhost` | Substituted for the absent `Tailscale-User-Login` header under `AUTH_MODE=dev`; set it to `BOOTSTRAP_ADMIN_LOGIN` to bootstrap locally |
| `TAILNET_IP` | `100.x.y.z` | Used for host-side port binding |
| `PROXY_HOSTNAME` | `llmapi.rcsl.online` | |
| `GATEWAY_BASE_URL` | empty | Where callers reach the inference API, shown in the management UI beside a newly issued key. Empty derives `https://` plus `PROXY_HOSTNAME`; set it only when the public origin differs. It cannot be read off the request, because the entrance answering is the admin one, not the one being described |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Not an environment variable: mounted as the `database_url` secret, a different least-privilege account per service ([security.md](../security.md) §6) |
| `REDIS_URL` | `redis://redis:6379/0` | The password is a separate `redis_password` secret |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Runtime on the host |
| `MLX_BASE_URL` | `http://host.docker.internal:8080` | The second host-native runtime, same reason (§1) |
| `MLX_TOOL_CALLING_VERIFIED` | `false` | Whether a real tool call has been seen against *this* `mlx_lm.server` build. It cannot be probed: a model that declines to call a tool is indistinguishable from a server that discarded the field, so only a person who has read a call off the wire may set it. While false the adapter refuses such a request rather than serving prose to an agent that will wait forever |
| `HF_CACHE_HOST_PATH` | `./data/hf-cache` | Host directory behind `HF_HOME`. On the Mac Studio it points at the `mlx_lm.server` account's `~/.cache/huggingface` — the operator's, since MLX did not move to a service account with Ollama on 2026-08-18 — so a model downloaded through the admin UI is the one the host-native server then serves. The one place a container writes onto a host path, and it holds model files only |
| `ADMIN_API_URL` | `http://admin-tailnet:8001` | Set per frontend service in Compose, not from `.env` |
| `ADMIN_BASE_URL` | `http://localhost:3000` | Origin used to build invitation and reset links. Configured rather than taken from the request: the link is issued on whichever entrance the administrator happens to be using and must always point at the public one, since a tailnet URL handed to somebody without Tailscale is a link they cannot open |
| `EXPOSE_OPENAPI` | `false` | Opt-in; ignored under `ENV=production` |
| `CACHE_BACKEND` | `redis` | `memory` is per-process and refused in production |
| `SESSION_ABSOLUTE_TTL_SECONDS` | `43200` | Names and units match the Settings fields |
| `SESSION_IDLE_TTL_SECONDS` | `3600` | |
| `INVITATION_TTL_SECONDS` | `259200` | Invitation and reset link lifetime |
| `TOTP_ENROLMENT_TTL_SECONDS` | `600` | How long a generated-but-unproved TOTP secret is held. Short on purpose: an abandoned enrolment must not leave a usable second factor waiting, and expiry costs the user only a re-scan |
| `TOTP_ISSUER` | `RCSL AI Nexus` | Shown by the authenticator app beside the account |
| `COOKIE_SECURE` | `true` | **Refused when `ENV=production` is set with `false`**, and it is not merely a flag: the `__Host-` prefix below requires `Secure`, so turning this off for local development drops the prefix as well and the frontend must be told the new cookie name (`NEXT_PUBLIC_CSRF_COOKIE=nexus_csrf`). The prefix is what binds the session cookie to this exact origin, which is the browser-side half of §4's argument for two hostnames and two entrances |
| `SESSION_COOKIE_NAME` | `__Host-nexus_session` | |
| `CSRF_COOKIE_NAME` | `__Host-nexus_csrf` | |
| `CSRF_HEADER_NAME` | `X-CSRF-Token` | Double-submit token, public entrance only |
| `ALLOWED_COUNTRIES` | `TW,AU` | Empty disables the filter |
| `MAX_CONTEXT_LENGTH` | `122880` | Bounds prompt size before generation starts, tool definitions and replayed tool calls included. Raised from `32768` on 2026-08-05, from `65536` on 2026-08-14 and from `98304` on 2026-08-17, each time for agent clients. **Sized together with `REQUEST_TIMEOUT_SECONDS` and the model's registered `context_length`**: prompt evaluation sends no bytes, so the read timeout is what bounds it. The 105.5 tok/s once quoted here was the dense model's and made that coupling look tight at 932s against the 1200s below; `qwen36-35b-a3b-q8` measured 711-730 tok/s across three cold session starts on 2026-08-17, so a full context is 173s and the read timeout is no longer the binding constraint; separately, Ollama evaluates at most `num_ctx / 2` prompt tokens and silently drops the rest, so this must stay under half of every serving model's registered context. **That invariant is no longer maintained here by hand, because it was not being maintained**: on 2026-08-17 this value was exactly half of `qwen36-35b-a3b-q8`'s `196608` rather than below it, and `assist` — which routes to `qwen7b` alone — was being served truncated at `8192 / 2` whenever a conversation reached a second turn. `RouteChatRequest._refuse_what_this_target_would_truncate` now applies the rule against whichever model routing picked, so this value bounds hardware cost and that one bounds correctness; `qwen7b` was raised to its native `32768` the same evening. Keep them consistent anyway — a global ceiling above a target's half turns a start-of-task refusal into a mid-task one |
| `OLLAMA_MODELS_PATH` | `/ollama-models` | Where the host's Ollama model store is mounted, read-only. The platform reads the vocabulary and the chat template out of the GGUF a model `ref` resolves to and counts prompts with them instead of estimating from character widths; only the metadata header is ever read (11.9 MiB in front of 38.7 GB of tensors). `OLLAMA_MODELS_HOST_PATH` is the host directory behind it. Empty turns exact counting off and falls back to the estimate — the right setting for a host that serves MLX and holds no GGUF — with a log line per model saying so |
| `TOKEN_COUNTER_CACHE_SIZE` | `2` | How many vocabularies one process keeps built. Measured: 132 MB resident for a 248,320-entry vocabulary and about 25 MB for a second. Two is what this deployment needs; eviction is least-recently-used and costs a rebuild of about a quarter of a second |
| `GEOIP_DB_PATH` | `/data/GeoLite2-Country.mmdb` | Refreshed weekly by `launchd/refresh-geolite2.sh` (runbook §5.1), which restarts the two enforcing services only when the file actually changed — geoip2 opens the database once at startup, so a swap alone changes nothing. Said "monthly" until 2026-08-03 and described no mechanism that existed |
| `BOOTSTRAP_ADMIN_LOGIN` | `you@example.com` | Creates the first admin on first login through the **tailnet** entrance only, and only while `users` is empty. Inert thereafter |
| `NODE_ID`, `NODE_NAME` | `local` | The single compute node `provision` writes on every start. There is no node-registration endpoint until the SSRF guard ships ([security.md](../security.md) §7.2) |
| `NODE_TOTAL_MEMORY_GB` | `64` | Must match the real machine, and is the figure `MemoryBudgetService` refuses loads against. Too high lets the guardrail walk the host into swap; too low refuses models that would fit ([../ARCHITECTURE.md](../../ARCHITECTURE.md) §0.2) |
| `NODE_HEARTBEAT_INTERVAL_SECONDS` | `30` | How often the admin entrances probe each node and write the observed status, so a routing requirement of `node_status: online` reflects reality rather than what provisioning wrote once. Admin entrances only — the gateway may not write `nodes` (§6 of [security.md](../security.md)). Zero or negative disables it |
| `MAX_CONCURRENT_INFERENCE` | `4` | Queueing depth, not throughput: the GPU serves one generation at a time |
| `QUEUE_WAIT_SECONDS` | `120` | How long a request may wait for a slot before `503 overloaded` with `Retry-After`. It exists because of the number two rows down: a slot can legitimately be held for 35 minutes, and before 2026-08-05 a caller arriving with every slot taken waited that long producing zero bytes and no code, which is indistinguishable from a hung deployment. §6 makes this class of setting the only line of defence, and a guardrail that refuses silently is half a guardrail. Zero or negative restores the unbounded queue |
| `MAX_TOKENS_CEILING` | `16384` | Counts a thinking model's reasoning as well as its answer |
| `GATEWAY_MAX_BODY_BYTES` | `4194304` | Request body ceiling, refused on `Content-Length` before a byte is read. **The one guardrail here that applies to callers who have not authenticated**: the key check is a FastAPI dependency and FastAPI parses the body before it resolves dependencies, so without this an anonymous caller reached an unbounded allocation — found 2026-08-07 by sending 200 MiB with no credential and being answered. Derived from `MAX_CONTEXT_LENGTH` rather than chosen, so raise it with that or not at all |
| `ADMIN_MAX_BODY_BYTES` | `41943040` | The admin entrances take uploads, so theirs is larger. It sits inside two orderings this document already argues: **above** the 32 MiB in `upload_policy.py`, so a file between the two is refused by the check that names the reason, and **below** the management host's nginx `client_max_body_size` (64m in §5) so ours is the limit that fires. The frontend's `middlewareClientMaxBodySize` must equal or exceed it — the hang described in [frontend.md](../frontend.md) §1 lived in exactly that gap |
| `OLLAMA_KEEP_ALIVE` | `-1` | Residency after a request. `-1` keeps the model loaded, making the registry's `loaded` state true; sent on every generation, since Ollama's own five-minute default applies to any request that omits it |
| `OLLAMA_THINKING` | `true` | Default only; a request's `think` field overrides it. `false` suppresses thinking. Never sends `think: true`: Ollama refuses it for models that do not support thinking |
| `REQUEST_TIMEOUT_SECONDS` | `1200` | Per-read HTTP timeout to the runtime: bounds a *stalled* stream, and therefore **prompt evaluation**, which sends no bytes. Raised from `300` on 2026-08-05 and from `600` on 2026-08-14, each time with the context ceiling above. The cost falls on a *hung* runtime rather than a busy one — a producing stream resets it on every chunk — so what it buys is that a cold full-context prefill is reachable at all |
| `GENERATION_DEADLINE_SECONDS` | `900` | Wall-clock bound on one generation, counted from the **first chunk** rather than the request, so reading a long prompt does not spend the budget for writing the answer. It therefore composes with the row above: one request's worst case is their sum, 2100 seconds — 35 minutes holding a concurrency slot, and the figure `QUEUE_WAIT_SECONDS` is argued against. The frontend's `experimental.proxyTimeout` must stay above the sum, or a cut arrives with no reason attached; it is 2,160,000 ms, which clears 2100 s by a minute |
| `METRICS_ENABLED` | `true` | Exposes `/metrics`; off lifts the production requirement for a real `metrics_scrape_token` |
| `PARSER_BASE_URL` | `http://parser:8000` | The isolated document parser. A sibling container on an internal network, deliberately *not* on `host.docker.internal` like the runtimes: this one must be able to reach nothing at all ([security.md](../security.md) §7.3) |
| `PARSER_TIMEOUT_SECONDS` | `120` | |
| `DOCUMENT_STORAGE_PATH` | `/var/lib/nexus/documents` | Inside the container, backed by the `documents` volume. A mounted volume rather than MinIO; see [../ARCHITECTURE.md](../../ARCHITECTURE.md) §4 for that decision and the condition that would reverse it |
| `QDRANT_BASE_URL` | `http://qdrant:6333` | The passage index. Its API key is a file secret, because Qdrant ships with no authentication at all |
| `QDRANT_TIMEOUT_SECONDS` | `30` | |
| `POSTGRES_USER`, `POSTGRES_DB` | `nexus` | Role and database names are not secrets; the superuser password is. Read by the `postgres` container |
| `API_KEY_MAX_LIFETIME_DAYS` | `3650` | Ceiling on how far ahead a key may be set to expire. Expiry exists to force rotation, and a mandatory field with no upper bound does not: an `expires_at` in the year 9999 satisfies "must be in the future" and rotates nothing. Raised from `365` to `3650` (10 years) on 2026-08-25. Also the figure the management assistant quotes |
| `ASSISTANT_MAX_TOKENS` | `1536` | Token ceiling for one advisory reply. Small on purpose: it answers in two or three sentences, and a reply that runs past the ceiling loses its proposal card rather than arriving malformed. The `assist` capability needs a routing policy of its own or the drawer reports it has no model to run on |

`API_KEY_PEPPER_PREVIOUS` was listed here until 2026-08-18 and is not an
environment variable: it is a file secret, empty except during a pepper
rotation, and it appears in the secrets table below. A secret named in both
tables is the one shape this section most needs to avoid, since an environment
variable outranks a file secret in pydantic-settings.

**Secrets** (`/run/secrets`, never environment variables)

Wired. `docker-compose.yml` declares a `secrets:` block backed by files under
`./secrets`, and each service mounts only what its role needs. `Settings` reads
them through `secrets_dir`. An environment variable outranks a file secret in
pydantic-settings, so a secret left in `.env` would silently override the mount;
`.env` therefore carries only non-secret configuration, and `secrets/README.md`
holds the setup. One file per credential, raw value, no trailing newline.

| Secret | Purpose | Mounted into |
|---|---|---|
| `owner_database_url` | Schema owner (DDL); URL | `migrate` only |
| `gateway_database_url` | Gateway account; URL. Writes `usage_records`, `prompt_logs` and `refusals` — this row said `usage_records` alone until 2026-08-18 — and reads every table **except** `prompt_logs` and `refusals`, which are subtracted from the blanket `SELECT` after it. The asymmetry is deliberate and is the whole of the argument: the one process exposed to the internet appends its own transcripts and refusals and can read none of them, which is the same split Qdrant's read-only key makes in the other direction. The names are in `db_roles.py`, in code, because they are a security decision that belongs under review rather than in a deployment file | `gateway`; and `migrate`, to provision the role |
| `admin_database_url` | Admin account (full DML, no DDL); URL | both admin entrances; and `migrate` |
| `postgres_password` | Superuser password; must equal the password in `owner_database_url` | `postgres` |
| `redis_password` | Read from the file in redis's command; no `_FILE` convention | `redis`, and the services that use redis |
| `api_key_pepper` | HMAC pepper | every backend service and `migrate` |
| `api_key_pepper_previous` | Accepted during a rotation, so keys signed with the old pepper keep verifying until they are reissued. Not shipped as a file, because it is empty except during one | none by default; add the secret and mount it into the backend services for the duration of a rotation |
| `totp_encryption_key` | Encrypts TOTP secrets at rest | backend services, `migrate` |
| `session_signing_key` | Present for completeness; sessions are opaque Redis ids | backend services, `migrate` |
| `proxy_shared_secret` | Matches `X-Nexus-Proxy` in nginx | backend services, `migrate` |
| `metrics_scrape_token` | Bearer token for `/metrics`; the same file is mounted into Prometheus | backend services, `migrate`, `prometheus` |
| `grafana_admin_password` | Grafana's initial admin password | `grafana` |
| `qdrant_api_key` | Qdrant's API key. It ships with **no authentication at all**, so this is not hardening but the only control between anything on the admin network and a full read of the knowledge base. Required to be a real value in production unconditionally, unlike `metrics_scrape_token` | `qdrant`, the two admin entrances, `migrate` |
| `qdrant_read_only_api_key` | A **different** value, and the vector store's half of the [security.md](../security.md) §6 least-privilege split. Mounted into `gateway` at the target name `qdrant_api_key`, so retrieving a passage to answer a request cannot become writing one. Verified against a live Qdrant: this key gets 200 on a search and 403 on a collection write | `qdrant`, `gateway` (as `qdrant_api_key`) |
| `alert_smtp_account` | The Gmail address `launchd/check-platform-health.sh` sends alerts *from*. Not itself a secret, but kept beside the password because Gmail requires the envelope sender to be the account that authenticates | no container; read from `./secrets` by the health daemon on the host |
| `alert_smtp_password` | A Google app password for that account, not the account password. Needs 2-Step Verification enabled on the account first | no container; the health daemon |
| `maxmind_license_key` | The MaxMind account's permanent licence key, read by `launchd/refresh-geolite2.sh`. The long-lived credential, unlike the throwaway token the first download used; without it `GEOIP_DB_PATH` rots in place, which is a country filter that quietly stops being current rather than one that fails | no container; the weekly refresh job |

**The last three are read by launchd jobs on the host, not mounted into any
container, and that is why this table did not list them until 2026-08-18.** The
table was assembled from `docker-compose.yml`'s `secrets:` block, which cannot
see them. Neither is needed if the corresponding daemon is not installed, and
`secrets/README.md` says so per file — but a deployment that copies only what is
listed here installs the health daemon and gets no mail, or installs the refresh
job and gets a fatal on its first run.

MinIO is absent and will stay absent: document storage is a mounted volume, not
object storage. See [ARCHITECTURE.md](../../ARCHITECTURE.md) §4 for that decision
and the condition that would reverse it.

The four crypto secrets, and `metrics_scrape_token` when metrics are enabled, are
mounted into `migrate` as well, because it calls `get_settings()`, which refuses
the shipped placeholders under `ENV=production`. `POSTGRES_USER` and `POSTGRES_DB`
stay non-secret environment values, read by the Postgres container.

`.env.example` lists every non-secret field with a development default, and
documents the secrets as file mounts rather than listing them, since a value
there would override the mount.
