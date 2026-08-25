"""Flat identity security setting declarations."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class IdentitySecuritySettings(BaseSettings):
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

    api_key_max_lifetime_days: int = 3650
    """Ceiling on how far ahead a key may be set to expire. 10 years, raised
    from 365 on 2026-08-25.

    Expiry exists to force rotation, and a mandatory field with no upper bound
    does not: `expires_at` of the year 9999 satisfied "must be in the future"
    and rotated nothing.

    Read by `build_manage_api_keys` and quoted to the operator by the management
    assistant. It was read by neither until 2026-07-29: the use case carried an
    identical default, so the two agreed by coincidence and changing this value
    did nothing at all.
    """
