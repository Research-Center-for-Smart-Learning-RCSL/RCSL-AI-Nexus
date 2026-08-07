"""Startup assertions that must never be downgraded to warnings.

Both cases here are silent total compromises if they reach production, and
neither is visible from the outside: an open admin API looks identical to a
working one until someone notices, and a placeholder pepper still verifies
keys correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.infrastructure.config import Settings

REAL_SECRETS = {
    "api_key_pepper": "real-pepper",
    "totp_encryption_key": "real-totp-key",
    "session_signing_key": "real-session-key",
    "proxy_shared_secret": "real-proxy-secret",
    "metrics_scrape_token": "real-metrics-token",
    "qdrant_api_key": "real-qdrant-key",
    "database_url": "postgresql+asyncpg://nexus:real@db:5432/nexus",
    "cache_backend": "redis",
}

# Settings reads ambient environment, so without this a developer's shell
# decides whether these pass. That is how CACHE_BACKEND=memory exported for an
# integration run made the production cases fail.
_AMBIENT = (
    "ENV",
    "AUTH_MODE",
    "CACHE_BACKEND",
    "DATABASE_URL",
    "REDIS_URL",
    "API_KEY_PEPPER",
    "TOTP_ENCRYPTION_KEY",
    "SESSION_SIGNING_KEY",
    "PROXY_SHARED_SECRET",
    "METRICS_SCRAPE_TOKEN",
    "METRICS_ENABLED",
    "QDRANT_API_KEY",
    "ALLOWED_COUNTRIES",
    "EXPOSE_OPENAPI",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    for name in _AMBIENT:
        monkeypatch.delenv(name, raising=False)
    # The repository's own .env would be read otherwise, for the same reason.
    monkeypatch.chdir(Path(__file__).resolve().parents[1])


def test_dev_auth_mode_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=dev"):
        Settings(env="production", auth_mode="dev", **REAL_SECRETS)


def test_dev_auth_mode_is_fine_in_development() -> None:
    settings = Settings(env="development", auth_mode="dev")
    assert settings.auth_mode == "dev"


@pytest.mark.parametrize("mode", ["tailnet", "local"])
def test_real_auth_modes_are_accepted_in_production(mode: str) -> None:
    settings = Settings(env="production", auth_mode=mode, **REAL_SECRETS)
    assert settings.is_production is True


def test_placeholder_secrets_are_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Placeholder secrets"):
        Settings(env="production", auth_mode="tailnet")


def test_placeholder_secrets_are_fine_in_development() -> None:
    settings = Settings(env="development", auth_mode="dev")
    assert "not-for-production" in settings.api_key_pepper


def test_allowed_countries_parsing() -> None:
    settings = Settings(allowed_countries=" tw , au ")
    assert settings.allowed_country_set == frozenset({"TW", "AU"})


def test_in_memory_cache_is_rejected_in_production() -> None:
    """Per-process counting would look like a rate limit without being one."""
    with pytest.raises(ValidationError, match="CACHE_BACKEND=memory"):
        Settings(
            **{
                **REAL_SECRETS,
                "env": "production",
                "auth_mode": "tailnet",
                "cache_backend": "memory",
            }
        )


def test_placeholder_metrics_token_is_rejected_only_when_metrics_are_enabled() -> None:
    """The scrape token guards /metrics, so a placeholder is a production defect
    when metrics are exposed. A deployment that runs no Prometheus turns them off
    and is not forced to invent a token it will not use."""
    base = {**REAL_SECRETS, "env": "production", "auth_mode": "tailnet"}
    placeholder = "dev-metrics-token-not-for-production"

    with pytest.raises(ValidationError, match="metrics_scrape_token"):
        Settings(**{**base, "metrics_scrape_token": placeholder})

    disabled = Settings(**{**base, "metrics_scrape_token": placeholder, "metrics_enabled": False})
    assert disabled.metrics_enabled is False


def test_the_qdrant_key_is_required_unconditionally() -> None:
    """Unlike the metrics token, there is no flag that makes this optional.

    Qdrant ships with no authentication at all, so a placeholder key leaves the
    whole knowledge base readable to anything that reaches the admin network.
    There is no deployment shape in which that is the intended state, so there
    is nothing to make it conditional on.
    """
    base = {**REAL_SECRETS, "env": "production", "auth_mode": "tailnet"}
    with pytest.raises(ValidationError, match="qdrant_api_key"):
        Settings(**{**base, "qdrant_api_key": "dev-qdrant-key-not-for-production"})


def test_a_placeholder_hidden_inside_a_url_is_caught() -> None:
    """The database password sits inside a connection string rather than
    standing alone, which is why it escaped the original check."""
    with pytest.raises(ValidationError, match="database_url"):
        Settings(
            **{
                **REAL_SECRETS,
                "env": "production",
                "auth_mode": "tailnet",
                "database_url": "postgresql+asyncpg://nexus:dev-postgres-not-for-production@db/nexus",
            }
        )


def test_the_schema_is_not_exposed_unless_explicitly_asked_for() -> None:
    """Gating on `not is_production` meant a deployment that filled in the
    secrets and left ENV at its default served its full internal schema."""
    assert Settings().expose_openapi is False
    assert Settings(expose_openapi_flag=True).expose_openapi is True
    assert (
        Settings(
            **{**REAL_SECRETS, "env": "production", "auth_mode": "tailnet"},
            expose_openapi_flag=True,
        ).expose_openapi
        is False
    ), "production wins over the flag"


def test_the_proxy_timeout_stays_above_the_generation_deadline() -> None:
    """Two files in two languages hold one ordering, and only a comment says so.

    The frontend proxies /admin/* with `NextResponse.rewrite`, and Next applies
    a socket timeout to a proxied request. Whichever of the two limits fires
    first decides what the caller sees: the backend's deadline ends the stream
    with `finish_reason=length`, while the proxy's resets the socket and leaves
    nothing in any log — which is exactly how a 93-second generation once
    surfaced in the browser as a 500 (PROGRESS, 2026-07-27).

    So the proxy's value must stay above the backend's, and raising the
    deadline without raising it would move that silent cut rather than remove
    it. Asserted here because a comment in each file cannot enforce an
    invariant that spans both.

    **The backend's figure is the read timeout plus the deadline, not the
    deadline alone.** Since 2026-08-05 the deadline is counted from the first
    chunk, so a long prompt can spend up to the read timeout being evaluated
    before its clock starts; the two compose rather than overlap. This test
    compared against the deadline alone and so kept passing while the proxy sat
    at 960s against a legitimate 1500s request — the original silent reset,
    moved from 30 seconds to 16 minutes, and invisible for exactly the reason
    the test exists.
    """
    root = Path(__file__).resolve().parents[3]

    # `encoding` is not optional here. `read_text()` without it decodes using
    # the process locale, which on a Windows development machine set to
    # Traditional Chinese is cp950, and both files carry UTF-8 punctuation in
    # their comments. The test then died on a `UnicodeDecodeError` rather than
    # on the invariant it exists to check, and only on machines whose locale
    # happened not to be UTF-8.
    config = (root / "frontend" / "next.config.js").read_text(encoding="utf-8")
    match = re.search(r"proxyTimeout:\s*([\d_]+)", config)
    assert match is not None, "proxyTimeout is gone; the 30s default is back"
    proxy_seconds = int(match.group(1).replace("_", "")) / 1000

    env = (root / ".env.example").read_text(encoding="utf-8")
    deadline_match = re.search(r"^GENERATION_DEADLINE_SECONDS=(\d+)", env, re.MULTILINE)
    assert deadline_match is not None, "the deadline must stay discoverable in .env.example"
    deadline = int(deadline_match.group(1))

    read_match = re.search(r"^REQUEST_TIMEOUT_SECONDS=(\d+)", env, re.MULTILINE)
    assert read_match is not None, "the read timeout must stay discoverable in .env.example"
    read_timeout = int(read_match.group(1))

    longest_request = read_timeout + deadline
    assert proxy_seconds > longest_request, (
        f"proxyTimeout ({proxy_seconds}s) must exceed the longest legitimate request: "
        f"{read_timeout}s of prompt evaluation plus {deadline}s of generation = "
        f"{longest_request}s, or a cut arrives with no reason attached"
    )
    assert deadline >= Settings().generation_deadline_seconds, (
        "the documented value must not be below the code default"
    )
    assert read_timeout >= Settings().request_timeout_seconds, (
        "the documented value must not be below the code default"
    )


def test_the_middleware_body_limit_stays_at_or_above_the_admin_ceiling() -> None:
    """The second invariant spanning these two files, and it hides a hang.

    Next's middleware matches `/admin/:path*`, so every admin request has its
    body passed through `getCloneableBody`. Past its limit that function does
    not reject: it pushes EOF into the stream forwarded upstream as well as the
    clone, and the caller's original `Content-Length` goes on unchanged. The
    backend is then waiting for bytes no one will send, until `proxyTimeout` —
    twenty-six minutes.

    So the failure lives in the *gap* between the two limits. Below the
    backend's ceiling, Next truncates a body the backend would have accepted;
    at or above it, the backend refuses on `Content-Length` before reading and
    the truncation cannot happen. Found on 2026-08-07, when a 12 MiB upload
    through the public entrance returned nothing at all while the same upload
    sent straight to the admin API answered in 0.16 s.

    Equality is the intended state rather than a coincidence to preserve: Next
    buffers up to this much in the Node process for a caller who has not
    authenticated, so the smallest value that closes the gap is the right one.
    """
    root = Path(__file__).resolve().parents[3]

    # See the note on encoding in the test above.
    config = (root / "frontend" / "next.config.js").read_text(encoding="utf-8")
    match = re.search(r"middlewareClientMaxBodySize:\s*([\d_]+)", config)
    assert match is not None, (
        "middlewareClientMaxBodySize is gone; the 10 MB default is back, and with it "
        "a silent truncation of every admin upload above it"
    )
    next_limit = int(match.group(1).replace("_", ""))

    env = (root / ".env.example").read_text(encoding="utf-8")
    admin_match = re.search(r"^ADMIN_MAX_BODY_BYTES=(\d+)", env, re.MULTILINE)
    assert admin_match is not None, "the admin ceiling must stay discoverable in .env.example"
    admin_limit = int(admin_match.group(1))

    assert next_limit >= admin_limit, (
        f"middlewareClientMaxBodySize ({next_limit}) must not sit below the backend's "
        f"ADMIN_MAX_BODY_BYTES ({admin_limit}): the difference is a range of upload sizes "
        f"that Next truncates and the backend then waits out, which is a hang rather than "
        f"an error"
    )
    assert admin_limit >= Settings().admin_max_body_bytes, (
        "the documented value must not be below the code default"
    )
