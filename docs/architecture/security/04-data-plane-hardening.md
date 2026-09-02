# 4. Data Plane Hardening

[← Security Architecture and Threat Model](../security.md)

### 4.1 Source Restriction

Public does not have to mean reachable by everyone. Since callers are known services, restricting sources shrinks exposure from "the entire internet" to "a list", and it is the highest-return control in this section.

| Layer | Mechanism | Enforced at | Strength | When |
|---|---|---|---|---|
| Application | Country allowlist (GeoIP) | Gateway and admin-public | Weak, noise reduction | Region is known, addresses are not |
| Proxy | nginx `allow` / `deny` | openresty | Strong | Caller addresses are fixed |
| Proxy | mTLS or shared-secret header | openresty | Strong | Caller addresses vary |
| Application | Per-key CIDR allowlist | Gateway | Strong | Whenever a key has a known origin |

**(a) Country allowlist, currently adopted.** Taiwan and Australia only.

Because the public entrance is openresty rather than a CDN, this is enforced **in the application** using the free MaxMind GeoLite2 database against the real client address resolved in [deployment.md](../deployment.md) §7:

```python
# interfaces/http/middleware/geo_filter.py
class GeoFilter:
    def __init__(self, allowed: frozenset[str], database_path: Path) -> None: ...

    def assert_allowed(self, client_ip: IPv4Address | IPv6Address) -> None:
        try:
            country = self._reader.country(str(client_ip)).country.iso_code
        except geoip2.errors.AddressNotFoundError:
            return                      # private and unrouted addresses: the
                                        # tailnet and the health probes
        if country not in self._allowed:
            logger.info("rejected request from %s (%s)", client_ip, country)
            raise CountryNotAllowedError(detail=f"country={country} ip={client_ip}")
```

The list is `ALLOWED_COUNTRIES` in configuration (`"TW,AU"`) rather than a
constant in the module, so the deployment that runs the filter is what decides
the countries — and `build_geo_filter` **refuses to start under `ENV=production`
when the setting is present and the GeoLite2 database is not**, rather than
serving every country while appearing configured. The two details the sketch
above used to omit are both refusals to guess: an address the database does not
know is allowed through, because rejecting it would break the tailnet and the
health probes, and the country that failed is logged rather than returned,
because telling a caller which rule rejected them is free reconnaissance.

**This filter applies to the public admin entrance as well as the gateway.** The control plane's worst-case damage is strictly greater, and its legitimate callers are a smaller and more predictable set, so there is no argument for restricting it less.

The cost of enforcing in the application is that traffic still reaches the Mac Studio before being rejected. The benefit is autonomy: no dependency on another administrator to install and maintain a GeoIP module. The GeoLite2 database needs monthly refresh; that belongs in the operations schedule.

**This is noise reduction, not a security boundary.** An attacker using a VPS or VPN in either country bypasses it completely, and GeoIP misclassification can block legitimate callers who are roaming. It remains worthwhile because the overwhelming majority of unsolicited traffic is automated scanning from a wide address distribution; removing it makes genuine anomalies visible in the logs. The real defences are the API key scheme (§4.2) and the resource guardrails (§4.3).

**(b) Fixed caller addresses: nginx allowlist.** Once callers are known, ask the proxy administrator for a default-deny allowlist:

```nginx
# in the llmapi.rcsl.online server block
allow 203.0.113.10;
allow 198.51.100.0/24;
deny  all;
```

**(c) Variable caller addresses: identify by credential, not location.** Cloud services and CI runners rotate egress addresses. Options in increasing strength: a shared secret header injected by openresty and verified by the gateway; or mTLS client certificates terminated at the proxy. Both are proxy-side changes requiring the other administrator.

**(d) Application layer: bind an address allowlist to each API key.** Do this regardless of what the proxy does, because it defends a different threat: **key leakage**. With only a country filter in place, this layer carries more weight.

```python
# domain/entities/api_key.py
allowed_cidrs: list[IPv4Network | IPv6Network]   # empty means unrestricted
```

A key committed to a public repository or leaked through logs is then unusable from anywhere else.

**Prerequisite: resolving the real client address.** Behind the proxy, `request.client.host` is not the caller. See [deployment.md](../deployment.md) §7, which also covers why the naive form of this check fails under Docker.

**Resulting exposure**

```
No restriction:    entire internet -> API key (sole defence)
Country filter:    TW + AU        -> API key + per-key CIDR -> quota      <- current
Address/credential: allowlist     -> API key + per-key CIDR -> quota      <- once callers are known
```

### 4.2 API Key Design

```python
# domain/services/api_key_service.py     token shape: nx_live_<key_id>.<secret>
KEY_PREFIX, SEPARATOR = "nx_live_", "."
KEY_ID_BYTES, SECRET_BYTES = 8, 32

def issue(self) -> IssuedKey:
    """The plaintext is shown once, at issue, and never recoverable afterwards."""
    key_id = secrets.token_hex(KEY_ID_BYTES)            # independent lookup handle
    secret = secrets.token_urlsafe(SECRET_BYTES)        # 256 bits of entropy
    plaintext = f"{KEY_PREFIX}{key_id}{SEPARATOR}{secret}"
    return IssuedKey(
        plaintext=plaintext,
        key_id=key_id,
        digest=hmac.new(self._peppers[0], plaintext.encode(), hashlib.sha256).hexdigest(),
    )
```

Deliberate choices:

- **SHA-256 HMAC rather than bcrypt or argon2.** Unlike a password, the key is a 256-bit random value, so brute force is infeasible regardless of hash speed and a slow KDF buys nothing. Meanwhile this code runs on every gateway request; bcrypt at roughly 100 ms per verification would destroy throughput.
- **A server-side pepper**, held in a mounted secret rather than the database. A database dump alone is not enough to forge a key.
- **A separate random `key_id` as the lookup handle**, not a prefix of the secret. An earlier draft stored the first 16 characters of the key in plaintext for indexing, which put part of the secret into logs and the database for no benefit and left collision handling undefined. `key_id` carries a unique index, appears in logs and in the UI for identification, and reveals nothing.
- **`key_id` travels inside the presented token**, after the prefix and before a dot, and this section's sketch omitted that until 2026-08-18 — which made the scheme as written unimplementable: with nothing but a digest on the wire, verification would have to scan every row and HMAC each one. The separator is a dot because `secrets.token_urlsafe` emits `[A-Za-z0-9_-]` and never a dot, so the split is unambiguous where an underscore would not be. A malformed token and an unknown one both return `None` from `parse_key_id`, so neither the response nor its timing distinguishes them.
- Comparison uses `hmac.compare_digest`, against **every** accepted pepper rather than only the current one, which is what makes the staged rotation below possible.

Bound metadata:

| Field | Purpose |
|---|---|
| `scopes` | Allowed capabilities, minimal by default. Carried onto `Actor.allowed_capabilities` and checked against the capability each request names; a key is refused, as 403, any capability it does not hold. This description was aspirational until 2026-07-28: the list decided only whether a key worked at all, so a key issued for `chat` reached every capability the deployment served ([PROGRESS.md](../../PROGRESS.md) 2026-07-28) |
| `default_capability` | What to serve when a request names a capability this key does not hold, or null to refuse — which is the default and what every key did before 2026-08-18. Constrained at issue, at edit and again at use to a capability already in `scopes`, so it is a substitution and never a widening: `Actor.capability_for` re-checks it rather than trusting the row, and a value outside the list decides nothing. Opt-in per key because the refusal it removes is load-bearing — `capability_not_issued` is the only channel that tells an integrator their client overrode the `model` line they configured. Every substituted request is announced to the caller in `X-Capability-Defaulted` and kept in `usage_records.requested_capability` |
| `rate_limit_rpm` | Requests per minute |
| `quota_tokens_per_day` | Daily token ceiling |
| `allowed_cidrs` | Source restriction, §4.1(d). Empty means unrestricted |
| `expires_at` | **Required**, `NOT NULL` in the schema. The issuing form defaults to 90 days and the use case refuses anything beyond **3650** (10 years, raised from 365 on 2026-08-25 to make room for long-lived integrations while keeping expiry mandatory), forcing rotation. The maximum reaches the caller as `maximum_days` on the refusal, for the reason §9.2 gives |
| `owner_id` | Which team member holds it, revoked when they leave |
| `revoked_at` | Revocation timestamp |
| `tenant_id` | The tenant the key belongs to, carried onto `Actor.tenant_id` so a key reaches only its own tenant's data (§7.3). Omitted from this table until 2026-08-18, though it is the field the whole isolation boundary rests on |
| `debug_logging_until` | The expiring full-logging and error-detail window, §9.2. A disclosure control living on the credential rather than on the platform |
| `name` | A label the owner chooses, shown in the UI. Attacker-controlled text that reaches a prompt when the assistant reads the screen, which is why §7.5 fences it |

There is deliberately **no `last_used_at`**. Keeping one current would mean the gateway writing to `api_keys` on every request, which is exactly what the account split in §6 exists to prevent; the same fact is derived from `usage_records`.

Revocation takes effect immediately, because every request re-reads the row. An earlier draft described a 60-second Redis verification cache; that was never built, and its absence is strictly safer, so it is recorded here as a deliberate non-feature rather than a gap. Adding it later would introduce a revocation window that has to be closed explicitly.

### 4.3 Resource Guardrails

Critical on this hardware. Under unified memory, **unbounded concurrent inference drives the machine into swap or thermal throttling**, and a public API means someone else can trigger it. With no edge protection (§3.1), this is the only line of defence.

| Guardrail | Setting | Why |
|---|---|---|
| Global inference concurrency | Semaphore sized to the deployment (`4`) | Queueing depth rather than throughput: the GPU serves one generation at a time, so this decides whether a caller waits or is refused |
| Per-request `max_tokens` | Hard cap (`16384`), overriding larger client requests | Bounds a single runaway generation. Counts a thinking model's reasoning as well as its answer, which is why it is not 4096 |
| Per-request context length | Hard cap | Memory cost grows non-linearly |
| Per-read request timeout | `1200` s | A stalled upstream (no bytes for the interval) fails fast rather than holding a slot. **This is also what bounds prompt evaluation**, which sends no bytes at all, so it is sized against the context cap above rather than chosen freely. 300 → 600 on 2026-08-05 and 600 → 1200 on 2026-08-14, each move made with the context ceiling; this row still said `600` on 2026-08-18, four days after the second one. The margin was read as widening: at the 117.9 tok/s measured on the dense model then serving, a 65536 context cost 556 s; at the 711-730 tok/s measured on `qwen36-35b-a3b-q8` on 2026-08-17, 122880 read as 173 s. **Both were shallow measurements against models that are not serving, and the margin is now negative.** `chat` and `code` went back to `gemma4:31b-it-q8_0` on 2026-08-21 without the ceiling being revisited, and prompt evaluation on it decays with depth — 209 tok/s over the first 10k tokens, 105 by 93k. Measured at the ceiling on 2026-09-02: **121,892 tokens at 88.4 tok/s is 1,379 s against this 1,200**, crossing near 110,000 tokens, so a prompt the context cap admits is cut off before a byte is sent. Options in [decisions.md](../../roadmap/decisions.md) |
| Wall-clock generation deadline | `900` s, from the **first chunk** | Bounds a slow-but-steady stream that stays under the per-read timeout yet never reaches the token cap; on unified memory near swap it would otherwise hold a slot for hours. Counted from the first chunk since 2026-08-05, so reading a long prompt does not spend the budget for writing the answer. The two therefore **compose**: one request's worst case is 2100 s, and the frontend's `experimental.proxyTimeout` must stay above that sum rather than above this row alone, or the cut arrives as a socket reset with no reason attached. It is `2_160_000` ms, and `test_config_failfast.py` reads both files and fails if it drops below the sum — which is what caught it being left at the old figure when the read timeout doubled |
| Cancel on client disconnect | Required | Otherwise generation continues for a departed client |
| Model memory budget | Loaded total must stay under a fraction of node capacity | Checked before load, refuses with a message to unload first |
| Runner context sizing | The model's registered `resource_profile.context_length`, sent to the runtime on load *and* on every generation | Told nothing, Ollama reserves for the model's own declared maximum: 55.8 GiB predicted for a 262144-token context on a deployment that never sends more than 65536, and it evicted every other resident model to fit — taking `assist` and `embedding` down with it. The registered value existed and reached nothing until 2026-08-07. `glm-4.7-flash`'s single KV head hid this for three months; the first dense model made it fatal on the first load |
| Request body ceiling | `4` MiB on the gateway, `40` MiB on the admin entrances | **The only row here that applies to a caller who has not authenticated**, and the reason it exists. Every other guardrail in this table is enforced inside `RouteChatRequest`, behind the key check — but that check is a FastAPI *dependency*, and FastAPI reads and JSON-parses the body before it resolves dependencies, so the allocation happened first. Measured, not inferred: 200 MiB with no credential, accepted in full ([PROGRESS.md](../../PROGRESS.md) 2026-08-07). `middleware/body_limit.py` |

The concurrency slot must be held for the entire generator lifetime, and disconnect cancellation must propagate all the way to the runtime adapter. Both are structural, not incidental; see [backend.md](../backend.md) §6.

**The body ceiling is the one guardrail that is not about inference at all, and it is placed where it is for a reason worth stating.** The other six bound what a *permitted* caller may consume; this one bounds what an anonymous one can. Anything moved behind authentication inherits the ordering defect it was written for, so it is stack-level ASGI middleware rather than a dependency or a check inside a use case, and it sits innermost so a request refused by it is still counted and still carries `X-Request-Id`.

**A guardrail that cannot be reached does not exist.** Two of the values above were
raised on 2026-07-27, and both changes were nearly inert. `MAX_TOKENS_CEILING` is
pinned in `.env`, which Compose loads and which outranks the code default, so
changing `config.py` alone would have shipped a fix that tested green and did
nothing. And the generation deadline is only the binding limit while the frontend's
proxy timeout sits above it; raising one without the other moves the failure to a
layer that reports no reason. The ordering between those two is asserted by a test
that reads both files, because a comment in each cannot enforce it.

The memory budget in Phase 1 is **static**: `nodes.total_memory_gb` times a headroom fraction of **0.8**, minus the sum over currently loaded models of `observed_memory_gb or resource_profile.memory_gb`, all from the database. Live metrics through `MetricsPort` arrive in Phase 2, and this check must not wait for them. Two things in that sentence were missing from it until 2026-08-18 and both change the arithmetic. The fifth of the machine held back is for the OS, the containers, and the inference working memory no resource profile counts — it is why the budget on this node is 51.2 of 64 GiB rather than 64. And **the heartbeat's observed figure outranks the declared profile** for anything already resident, because it includes the KV cache the profile does not: 5.7 GB measured against 4.7 GB of declared weights for a 7B model. The declared figure remains the estimate for the model being loaded, which nothing has observed yet, and for anything the heartbeat has not seen.

The Phase 2 observability stack (Prometheus and Grafana, §13.0) ships the *emission* side: each application exposes what it is doing at `/metrics`. It does not yet change this check. The `MetricsPort` the budget would read is the *ingestion* side, a live free-memory figure for the node, and a real one only exists on the Mac Studio. So the budget stays static and authoritative until that figure is real, which is the conservative reading of the rule above rather than a gap.

**Free memory on this node swings between roughly 12 GB and 37 GB depending on whether it is serving, and that is a measured property rather than a fault — OPEN, 2026-08-05, nothing changed.** Three models are held resident permanently by `OLLAMA_KEEP_ALIVE=-1` (`/api/ps` reports `expires_at` in the year 2318), totalling 44.4 GB. Inference **wires** those pages within about a second; idle, they revert to clean **file-backed** pages of the mmapped blob, which the OS is free to evict and re-fault from SSD. Measured on this machine: 40.6 GB wired and 12.1 GB available while serving, 2.3 GB wired and 37.2 GB available after twenty minutes idle, with nothing unloaded in between.

Three consequences for this section. **A single sample of free memory is not a capacity measurement** — the host status screen shows whichever moment it is opened, and the alarming reading is the normal one taken during work. **The static budget's conservatism is doing real work here**, since the figure it would replace is this volatile. And the length of the wiring tail decides whether 12 or 37 is what a second concurrent load should be planned against.

**The tail is 19 minutes, measured twice on 2026-08-07** ([PROGRESS.md](../../PROGRESS.md) 2026-08-07). Two runs forty minutes apart put the release inside (1139, 1151] seconds — 18.99 to 19.18 minutes — agreeing within three seconds on the lower bound. Three things follow that the old bound of ">20 s, <~20 min" did not give:

- **The trigger is a single request of any size.** A 0.9-second, two-token generation wired 38.5 GB within one sample. "12 GB" is not what this machine looks like under load; it is what it looks like for nineteen minutes after anything at all.
- **The release is a change of page status, not a reclaim.** Wired fell 38.3 GB and file-backed rose 31.8 GB in the same interval while *free* did not move. Nothing was handed back because nothing had been taken. `ollama.log` is silent at both release moments, so this is the OS rather than the runtime.
- **Nineteen minutes at 0.1–0.7 GB free with swap at 0 bytes, and nothing degraded**, across 79 and 76 consecutive samples. The alarming figure is not a symptom of the state this section's guardrails exist to prevent.

**The shape is per session rather than steady**, and `usage_records` says so: of 181 gaps between consecutive requests, 152 are under nineteen minutes. So the tail never expires inside a working session and the machine sits at ~12 GB throughout it; between sessions it returns to ~37 GB. Sampling time and usage time are therefore correlated — anyone opening the host status screen is by definition using the platform, so it will usually show them the low number. That is worth knowing before it is read as a fault.

One number remains unverified and bears on this row: whether the OS actually evicts those file-backed pages under pressure rather than merely being free to, which needs a deliberate allocation on a serving machine and is a decision rather than a measurement.

**The second open question here — whether headroom survives at the context ceiling — was measured on 2026-08-14 and the answer changed a registered figure.** `llama-server`'s resident size is `num_ctx`-dependent and the registry's `memory_gb` never counted it: 37.34 GiB at `num_ctx=131072`, 40.40 at `196608`, 42.93 at `262144`, against a declared profile of 32 GiB that is the weights alone. Ollama's own `size_vram` reports 31.58 GiB at all three, so **the runtime's figure cannot be used to find this** and `observed_memory_gb` under-counts by the whole KV cache. The KV cost is linear rather than superlinear in context — about 44 KiB per token on this model — which is the opposite of what this row assumed. `gemma4-31b-q8`'s profile was corrected to 41 GiB with the context raise, putting the three loaded models at 47 of the 51.2 GiB budget.

**What was recorded here as a third, unexplained number is not one — it is two units.** Ollama's 38.3 GB for `glm-4.7-flash` and the heartbeat's stored 35.7 are the same 38,300,454,748 bytes divided by `1e9` and by `1024³`; `ollama_adapter.py` stores GiB. The real gap is the declared 32 against the observed 35.67 GiB, and the KV cache explained that on 2026-07-30. The units are consistent where they matter: `hw.memsize` is exactly 64.00 GiB, so `nodes.total_memory_gb = 64` is a GiB figure and the budget below is not mixing scales.

**An earlier version of this paragraph said the weights are wired and therefore permanently unreclaimable by swap, compression or eviction.** It was recorded as inferred-not-proven, was checked because of that label, and was false within the hour. See [PROGRESS.md](../../PROGRESS.md) 2026-08-05, which keeps the wrong version and the experiment that killed it.

### 4.4 General Public Service Hardening

- No version numbers in responses; `debug=False`; error bodies never carry stack traces, internal model names, or node addresses. Enforced centrally by the error mapping in [backend.md](../backend.md) §5.
- Strict CORS allowlist, never `*`. In practice the frontend is same-origin via Next.js rewrites ([frontend.md](../frontend.md) §1), so CORS should not be needed at all; if a configuration seems to require it, that is a signal something is misrouted.
- Request body size limits, at every layer that can impose one, ordered so the innermost fires. From the outside in on the management host: nginx `64m`, Next's `middlewareClientMaxBodySize` 40 MiB, the application's `ADMIN_MAX_BODY_BYTES` 40 MiB, and `upload_policy.MAX_UPLOAD_BYTES` 32 MiB, which is the only one that names the reason. **The ordering is load-bearing in both directions**: a layer smaller than the one inside it either pre-empts the error that explains itself (nginx's HTML 413) or, in Next's case, truncates the body and forwards the original `Content-Length` so the backend waits it out — a hang rather than an error, which is what 10 MB to 32 MiB did until 2026-08-07 ([frontend.md](../frontend.md) §1). **This line claimed a control that did not exist on either side, and said so in the present tense from the start.** On 2026-08-07 the application had no ceiling at all, and `client_max_body_size` was unset on the inference host — a 200 MiB body from an unauthenticated caller was accepted and passed through. The application half now exists (`middleware/body_limit.py`, §4.3); the nginx half is an open item in [ROADMAP.md](../../ROADMAP.md). They are not redundant: nginx keeps the bytes off the machine, the middleware keeps them out of the process, and only the second is a control this deployment can verify or restore by itself.
- **`Cache-Control: no-store` on every response that does not choose its own**, on all three applications (`middleware/cache_control.py`, added 2026-08-18). Before that only two responses said anything about storage — an SSE stream and the enrolment QR — and each because somebody was thinking about that one response; the admin API returned users, keys, audit rows, transcripts and refusals saying nothing, and so did the gateway, whose responses carry a prompt and a completion. A cache told nothing is not forbidden from storing, and §15.1's proxy is a cache-capable intermediary this deployment does not administer. "It is probably not configured to cache" is the same argument as "nginx probably limits the body size", which the bullet above records being wrong about by 200 MiB. It never overwrites a header a response set for itself, because widening the stream's `no-cache` to `no-store` is a separate decision about how intermediaries buffer; and an exception that escapes to Starlette's `ServerErrorMiddleware` is answered outside every user middleware and does not carry it, which is narrow because all three applications install their own handlers.
- **`/openapi.json` and `/docs` are disabled on the gateway** and served only by the admin applications. Public API documentation is written separately rather than exposing internal schemas. That documentation now exists, as the `/api-docs` page of the management UI: the endpoint, the bearer header, the capability-rather-than-model convention, the request fields and the error code table. Until 2026-07-28 it did not, which made this a trade with nothing on the other side of it — an integrator had no description of the wire contract from any source. The page renders the live base URL and capability list rather than prose, so it cannot describe a deployment other than the one serving it. `GET /v1/models` answers the same question on the wire, for client libraries that ask before a person does.

  **The trade is only as good as the page is complete, and on 2026-07-30 it was audited against the wire for the first time.** Everything the page said was accurate; five things it did not say were not. The one that mattered here rather than in [ROADMAP.md](../../ROADMAP.md) was that `use_knowledge` and `knowledge_collection` are part of the gateway's public request schema and the page never mentioned them — so a capability of this deployment was reachable by anyone who guessed the field name and discoverable by nobody who read the documentation, which is the opposite of what disabling the schema endpoints was meant to achieve. Also missing: that `temperature`, `top_p`, `n`, `stop`, `tools` and `response_format` were accepted and silently ignored; that a stream failing after the first byte is a 200 carrying an error frame with no `[DONE]`; that streaming reported no usage at all; and five reachable error codes. Recorded in [PROGRESS.md](../../PROGRESS.md) 2026-07-30.

  **Closed on 2026-08-03, except one.** Grounding, the ignored fields, the mid-stream failure shape, `prompt_tokens` and four of the five codes are all on the page now, and the tool-calling work of 2026-08-05 turned three of those documented absences into behaviours — `tools` and the sampling fields are honoured, and `stream_options: {"include_usage": true}` adds a final usage frame — each stated on the page with the date it changed rather than quietly rewritten. What is still absent is **`vector_store_unavailable`**, which is reachable (`VectorStoreError`, "The knowledge index is not available") and has no row in the page's error table, so the one code a grounded request can fail with is the one code the grounding documentation does not name. This paragraph read as though nothing had been closed until 2026-08-18, which is its own version of the defect it was written about.
