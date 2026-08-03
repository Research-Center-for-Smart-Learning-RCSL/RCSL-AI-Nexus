"""Application settings.

Non-secret configuration comes from environment variables; secrets are
mounted as files and read through `secrets_dir`, because environment
variables show up in `docker inspect` output and in the process list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["tailnet", "local", "dev"]
Environment = Literal["development", "production"]
CacheBackend = Literal["redis", "memory"]

SECRETS_DIR = Path("/run/secrets")
_secrets_dir = str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None
"""Docker mounts secrets here; a developer machine has no such directory and
pydantic-settings warns on every instantiation if pointed at a missing path."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir=_secrets_dir,
        extra="ignore",
        populate_by_name=True,
    )

    env: Environment = "development"
    auth_mode: AuthMode = "dev"
    expose_openapi_flag: bool = Field(default=False, alias="EXPOSE_OPENAPI")

    log_level: str = Field(
        default="INFO",
        description=(
            "Level for the application's own `app.*` loggers, not the root. "
            "INFO by default because the lines below WARNING are the ones that "
            "say *why* a request was refused — `perimeter_rejected` is the only "
            "place the three causes of `untrusted_proxy` are distinguished. "
            "Nothing configured logging at all before 2026-08-03, which meant "
            "Python's WARNING-level fallback handler discarded every one of "
            "them (infrastructure/logging_config.py)."
        ),
    )

    tailnet_ip: str = "127.0.0.1"
    proxy_hostname: str = "api.nexus.rcsl.online"

    admin_base_url: str = "http://localhost:3000"
    """Origin of the management UI, used to build invitation and reset links.

    Configured rather than derived from the request, because the link is issued
    on whichever entrance the administrator is using and must always point at
    the public one: a tailnet URL handed to someone who has no Tailscale is a
    link they cannot open.
    """

    gateway_base_url_override: str = Field(default="", alias="GATEWAY_BASE_URL")
    """Where callers reach the inference API, shown in the management UI beside
    a newly issued key.

    Set only when the public origin is not `https://` plus `PROXY_HOSTNAME` —
    a different port in development, say. Empty means "derive it", so the two
    cannot drift apart in the ordinary deployment where they agree.

    It is configuration rather than something read off the request because the
    UI asking is on the *admin* origin: the request that renders the snippet
    arrives at a different host from the one the snippet must name.
    """

    database_url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    """A request holds a connection for its whole duration, and an audited one
    needs a second, so the pool must exceed the concurrent request count rather
    than sit near it. 30 across three services stays under Postgres's default
    100 max_connections. See infrastructure/db.py."""
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    cache_backend: CacheBackend = "redis"
    """`memory` is per-process and therefore wrong for anything counted across
    workers. Chosen explicitly, never inferred, so it cannot be reached in a
    deployment by accident."""

    ollama_base_url: str = "http://host.docker.internal:11434"
    mlx_base_url: str = "http://host.docker.internal:8080"
    """`mlx_lm.server` on the host, reached the same way as Ollama. Downloads it
    triggers land under HF_HOME, which the Compose file bind-mounts onto the host
    HuggingFace cache the native server reads; see adapters/runtime/mlx_adapter.py."""

    node_id: str = "local"
    node_name: str = "local"
    node_total_memory_gb: float = 64.0
    node_heartbeat_interval_seconds: int = 30
    """How often the admin app probes each node and writes the observed status,
    so a routing requirement of an online node reflects reality rather than the
    value provisioning wrote once. Zero or negative disables the loop."""
    """Capacity of the machine the runtimes are on.

    The memory budget refuses a load that would exceed a fraction of this, and
    it is static in Phase 1 because `MetricsPort` is Phase 2. **It must match
    the real machine**: too high and the guardrail lets the host into swap,
    too low and models that would fit are refused.

    The node is configured rather than registered through the API because
    Phase 1 is single-node, and a node write endpoint has to ship alongside
    the SSRF guard: registering a node means storing an address the platform
    will then make requests to. See docs/architecture/security.md section 7.2.
    """

    session_absolute_ttl_seconds: int = 12 * 3600
    session_idle_ttl_seconds: int = 3600
    invitation_ttl_seconds: int = 72 * 3600
    totp_enrolment_ttl_seconds: int = 600

    totp_issuer: str = "RCSL AI Nexus"
    """Shown by the authenticator app next to the account. Changing it after
    people have enrolled only relabels new enrolments; existing ones keep the
    name they were provisioned with."""

    session_cookie_name: str = "__Host-nexus_session"
    csrf_cookie_name: str = "__Host-nexus_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    cookie_secure: bool = True

    dev_tailnet_login: str = "dev@localhost"
    """Stands in for the `Tailscale-User-Login` header under `AUTH_MODE=dev`.

    Substituting the header rather than fabricating an actor is deliberate:
    the request then travels the same resolution and bootstrap path it would
    in production, against a real `users` row with a real id that foreign keys
    can reference. A synthetic actor would exercise neither, and would fail
    the first time anything tried to record who owns an API key.
    """

    allowed_countries: str = "TW,AU"
    geoip_db_path: str = "/data/GeoLite2-Country.mmdb"

    bootstrap_admin_login: str = ""

    max_concurrent_inference: int = 4
    """Sized to the deployment: a lab whose peak is four people at once.

    Note what it does not buy. The GPU serves one generation at a time, so a
    fourth slot is queueing depth, not throughput — it decides whether a fourth
    caller waits or is refused, and waiting is the better answer at this size.
    """

    max_tokens_ceiling: int = 16384
    """Hard ceiling on tokens per generation, thinking included.

    4096 → 8192 → 16384. `eval_count` counts reasoning, and a thinking model
    can spend an entire budget deliberating: GLM-4.7-Flash produced 8192 tokens
    of reasoning on a three-guards logic puzzle and no answer, twice.

    Raising it does not fix that case and was not meant to — the same question
    ran to 23,632 tokens without answering, so no affordable ceiling would.
    What it buys is room for legitimate long answers now that reasoning shares
    the budget. The case that will not converge is bounded by the wall-clock
    deadline below and by `think: false`, which answered that same question in
    49 seconds.
    """

    ollama_keep_alive: str = "-1"
    """How long Ollama keeps a model resident after serving a request.

    `-1` keeps it until something asks otherwise, which is what makes the
    registry's `loaded` state true rather than aspirational: the row says
    loaded, the memory budget reserves the weights, and `unload` is the release
    path. A duration such as `10m` is also accepted.

    Sent on every generation, not only on load. Ollama applies its own default
    (five minutes) to any request that omits the field, so a generate without it
    silently overwrites what `load` asked for — measured as 14 reloads in a day
    while the configured value was `10m` and never once in force.
    """

    ollama_thinking: bool = True
    """The default for a request that expresses no preference.

    Per-request `think` overrides it (chat_schemas.py). Only ever expressed as
    a suppression: `think: false` is sent when thinking is off, and nothing is
    sent when it is on, because Ollama rejects `think: true` for a model that
    does not support it. Graded values are not offered — `think: "low"` is
    accepted by Ollama and measurably changes nothing.
    """
    max_context_length: int = 32768
    request_timeout_seconds: int = 300
    generation_deadline_seconds: int = 900
    """Wall-clock ceiling on a single generation while it holds a concurrency slot.

    Raised from 600 with the token ceiling, so that the ceiling is what binds a
    long answer rather than this. Throughput decays badly with context on this
    hardware — 60.8 tok/s at the start of a generation, 23.5 by the 16000th
    token, measured — which puts a full 16384-token generation at roughly 700
    seconds. At 600 this cut first, and a limit that fires before the one it is
    meant to backstop reports the wrong reason.

    It is still a real bound: fifteen minutes is the longest one caller can
    hold one of four slots.

    Distinct from `request_timeout_seconds`, which is the per-read HTTP timeout:
    that bounds a stalled stream (no bytes for the interval), while this bounds a
    stream that keeps producing slowly enough to stay under it yet below the token
    ceiling. On unified memory near swap that case can hold a slot for hours, and
    with only `max_concurrent_inference` slots and no edge protection it is the one
    guardrail the other three do not cover. Zero or negative disables it. The
    stream is cut with `finish_reason=length`, the honest signal to an OpenAI
    client that the model did not finish."""

    api_key_max_lifetime_days: int = 365
    """Ceiling on how far ahead a key may be set to expire.

    Expiry exists to force rotation, and a mandatory field with no upper bound
    does not: `expires_at` of the year 9999 satisfied "must be in the future"
    and rotated nothing.

    Read by `build_manage_api_keys` and quoted to the operator by the management
    assistant. It was read by neither until 2026-07-29: the use case carried an
    identical default, so the two agreed by coincidence and changing this value
    did nothing at all.
    """

    assistant_max_tokens: int = 1536
    """Token ceiling for one management assistant reply.

    Far below `max_tokens_ceiling`, because the two are answering different
    questions. That one is the most the hardware should ever spend on a
    generation; this is the most a two-or-three-sentence answer in a drawer
    could possibly need, and a ceiling near the length of a good answer turns a
    model that has started rambling into a cut-off paragraph rather than ten
    minutes of held concurrency slot.

    It bounds the proposal too. A block that runs past the ceiling arrives
    unterminated and is discarded, so the visible cost of setting this too low
    is a card that does not appear, not a malformed one that does.
    """

    document_storage_path: str = "/var/lib/nexus/documents"
    """Where uploaded documents and their extracted text are kept.

    A mounted volume rather than MinIO, decided when the knowledge base was
    built: one node, one filesystem, and MinIO would have added a service, a set
    of default credentials to replace, and a CVE surface for features this
    deployment does not use. See ARCHITECTURE.md section 6 and
    adapters/storage/filesystem_documents.py.
    """

    parser_base_url: str = "http://parser:8000"
    """The isolated document parser (app/parser/main.py). A sibling container on
    an internal network, unlike the runtimes, which are on the host: this one
    must reach nothing, so it is deliberately not on `host.docker.internal`."""

    parser_timeout_seconds: int = 120

    qdrant_base_url: str = "http://qdrant:6333"
    qdrant_timeout_seconds: int = 30
    """The passage index. Reached over its REST API rather than through
    `qdrant-client`, which would pull grpcio and protobuf into an image that
    needs neither; see adapters/vector/qdrant_store.py."""

    metrics_enabled: bool = True
    """Whether each application exposes `/metrics` for Prometheus. On by default;
    an operator who runs no Prometheus can turn it off, which also lifts the
    production requirement below that its scrape token be a real value."""

    api_key_pepper: str = Field(default="dev-pepper-not-for-production")
    api_key_pepper_previous: str = Field(
        default="",
        description="Set during a pepper rotation so keys signed with the old "
        "value keep verifying until they are reissued.",
    )
    totp_encryption_key: str = Field(default="dev-totp-key-not-for-production")
    session_signing_key: str = Field(default="dev-session-key-not-for-production")
    proxy_shared_secret: str = Field(default="dev-proxy-secret-not-for-production")
    qdrant_api_key: str = Field(default="dev-qdrant-key-not-for-production")
    """Qdrant ships with **no authentication at all** (security.md section 10),
    and the whole knowledge base is readable to anything that reaches it. Set
    through `QDRANT__SERVICE__API_KEY` on the service and read from the same
    file secret here, so the two cannot drift."""

    metrics_scrape_token: str = Field(default="dev-metrics-token-not-for-production")
    """Bearer token Prometheus presents to `/metrics`. A secret, so it is a file
    mount like the rest; required to be a real value in production only when
    `metrics_enabled` is set. See interfaces/http/routers/metrics.py."""

    @property
    def allowed_country_set(self) -> frozenset[str]:
        return frozenset(c.strip().upper() for c in self.allowed_countries.split(",") if c.strip())

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def effective_session_cookie(self) -> str:
        return _drop_host_prefix_if_insecure(self.session_cookie_name, self.cookie_secure)

    @property
    def effective_csrf_cookie(self) -> str:
        return _drop_host_prefix_if_insecure(self.csrf_cookie_name, self.cookie_secure)

    @property
    def expose_openapi(self) -> bool:
        """Schema and Swagger UI on the gateway.

        Gated on an explicit opt-in rather than on `not is_production`. The
        default `ENV` is `development`, and `.env.example` ships it, so a
        deployment that filled in the secrets and left the top of the file
        alone was serving its full internal schema publicly. Requiring a
        deliberate `EXPOSE_OPENAPI=true` means forgetting fails closed.
        """
        return self.expose_openapi_flag and not self.is_production

    @property
    def gateway_base_url(self) -> str:
        """The origin an integrator points a client library at.

        Derived from `PROXY_HOSTNAME` unless overridden, so the ordinary
        deployment configures the hostname once. No trailing slash: callers
        append `/v1/...`, and the snippets shown in the UI are copied verbatim.

        A bare hostname in the override is completed rather than passed
        through. `GATEWAY_BASE_URL=api.example.com` yields `api.example.com/v1`,
        which no client library can use, and the failure appears in somebody
        else's terminal long after the setting was written.
        """
        origin = self.gateway_base_url_override.strip() or f"https://{self.proxy_hostname}"
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        return origin.rstrip("/")

    @model_validator(mode="after")
    def _refuse_dev_auth_in_production(self) -> Settings:
        """Fail fast rather than silently serving an unauthenticated admin API.

        `AUTH_MODE=dev` injects a fixed admin actor and disables the geo and
        trusted-proxy checks, which is the only way the stack runs on a
        developer machine. A deployment that reaches production with it still
        set must refuse to boot; a warning would be missed.
        """
        if self.env == "production" and self.auth_mode == "dev":
            raise ValueError(
                "AUTH_MODE=dev cannot be used with ENV=production: it bypasses "
                "authentication entirely. Set AUTH_MODE to 'tailnet' or 'local'."
            )
        return self

    @model_validator(mode="after")
    def _refuse_placeholder_secrets_in_production(self) -> Settings:
        """The default secrets are development placeholders and are committed
        to the repository in .env.example. Reaching production with one still
        in place would be a silent, total compromise of that mechanism."""
        if not self.is_production:
            return self

        placeholders = {
            "api_key_pepper": self.api_key_pepper,
            "totp_encryption_key": self.totp_encryption_key,
            "session_signing_key": self.session_signing_key,
            "proxy_shared_secret": self.proxy_shared_secret,
            # Included because the placeholder is embedded in a URL rather than
            # standing alone, which is exactly why it was missed before.
            "database_url": self.database_url,
            # Unconditional, unlike the metrics token below: an unauthenticated
            # Qdrant on the admin network is a full read of the knowledge base
            # for anything that gets onto it, and there is no deployment shape
            # in which the placeholder is acceptable.
            "qdrant_api_key": self.qdrant_api_key,
        }
        # Only when metrics are actually exposed: a deployment that runs no
        # Prometheus has no token to protect and should not be forced to invent one.
        if self.metrics_enabled:
            placeholders["metrics_scrape_token"] = self.metrics_scrape_token
        offenders = [name for name, value in placeholders.items() if "not-for-production" in value]
        if offenders:
            raise ValueError(
                f"Placeholder secrets present in production: {', '.join(sorted(offenders))}. "
                "Mount real values under /run/secrets."
            )
        return self

    @model_validator(mode="after")
    def _refuse_insecure_cookies_in_production(self) -> Settings:
        """Without `Secure`, the session cookie is sent over plain HTTP and the
        `__Host-` prefix is dropped, which removes both the transport guarantee
        and the same-origin binding that prefix provides. The setting exists
        only so the public entrance can be exercised locally."""
        if self.is_production and not self.cookie_secure:
            raise ValueError(
                "COOKIE_SECURE=false cannot be used with ENV=production: the "
                "session cookie would travel in clear text."
            )
        return self

    @model_validator(mode="after")
    def _refuse_in_memory_cache_in_production(self) -> Settings:
        """An in-memory cache silently makes rate limits per-worker, so a
        deployment would appear to enforce a limit it does not."""
        if self.is_production and self.cache_backend == "memory":
            raise ValueError(
                "CACHE_BACKEND=memory cannot be used with ENV=production: rate "
                "limits would be counted per process rather than per key."
            )
        return self


HOST_COOKIE_PREFIX = "__Host-"


def _drop_host_prefix_if_insecure(name: str, secure: bool) -> str:
    """Browsers reject a `__Host-` cookie that is not also `Secure`.

    Local development of the public entrance runs over plain HTTP, where
    keeping the prefix would mean the cookie is silently discarded and the
    login appears to succeed and then immediately fail. Dropping it is
    confined to that case: `cookie_secure` cannot be false in production.

    The frontend reads the CSRF cookie by name, so a developer who turns this
    off must set `NEXT_PUBLIC_CSRF_COOKIE` to match. Recorded in .env.example.
    """
    if secure or not name.startswith(HOST_COOKIE_PREFIX):
        return name
    return name[len(HOST_COOKIE_PREFIX) :]


@lru_cache
def get_settings() -> Settings:
    return Settings()
