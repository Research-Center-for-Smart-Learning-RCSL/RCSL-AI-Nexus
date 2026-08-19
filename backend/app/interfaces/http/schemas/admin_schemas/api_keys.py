"""Admin api keys schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.entities.api_key import ApiKey

from .shared import UtcDatetime


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    scopes: list[str]
    rate_limit_rpm: int
    quota_tokens_per_day: int
    allowed_cidrs: list[str]
    expires_at: datetime
    owner_id: str
    owner_display: str | None
    revoked_at: datetime | None
    created_at: datetime | None
    last_used_at: datetime | None
    """Derived from `usage_records`, not stored on the key. Maintaining a
    column would put a write to `api_keys` on the gateway's hot path, which
    the account split exists to prevent."""

    debug_logging_until: datetime | None
    """While this is in the future, error responses to this key carry
    operator-facing `detail`. Null or past means the normal rule applies:
    detail stays in the log. Set via POST /{key_id}/debug."""

    default_capability: str | None
    """Served when a caller names a capability this key was not issued for.

    Null is the default and the behaviour every key had before the field
    existed: refuse, and say what the key may call. Always one of `scopes`,
    which is what makes it a shortcut rather than a grant.
    """

    @classmethod
    def of(
        cls,
        key: ApiKey,
        *,
        owner_display: str | None = None,
        last_used_at: datetime | None = None,
    ) -> ApiKeyResponse:
        return cls(
            # The digest is absent, and there is no field for it. A response
            # model that cannot express the secret cannot leak it by accident.
            key_id=key.key_id,
            name=key.name,
            scopes=sorted(key.scopes),
            rate_limit_rpm=key.rate_limit_rpm,
            # The frontend treats this as a plain number; zero reads as "no
            # quota", which is what None means here.
            quota_tokens_per_day=key.quota_tokens_per_day or 0,
            allowed_cidrs=[str(n) for n in key.allowed_cidrs],
            expires_at=key.expires_at,
            owner_id=key.owner_id,
            owner_display=owner_display,
            revoked_at=key.revoked_at,
            created_at=key.created_at,
            debug_logging_until=key.debug_logging_until,
            default_capability=key.default_capability,
            last_used_at=last_used_at,
        )


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    owner_id: str = Field(min_length=1, max_length=36)
    scopes: list[str] = Field(min_length=1)
    rate_limit_rpm: int = Field(ge=1, le=100_000)
    """`ge=1`, not `ge=0`. The gateway reads `rate_limit_rpm <= 0` as **no
    limit** (`middleware/api_key_auth.py`), so zero was a way to issue an
    unmetered key through a form that reads as if it were tightening one. The
    frontend already declares this positive; the backend was the looser of the
    two."""

    quota_tokens_per_day: int = Field(ge=1)
    """Same reasoning, plus the two verbs disagreed: on create the router
    mapped `0` to `None` (no quota at all), while on update `0` was stored
    literally and refused every request forever. Zero is now inexpressible.

    `_per_day` names the size of the window, not a reset time: it is the
    trailing 24 hours, so nothing about it happens at midnight. Sizing it needs
    the prompt in mind, because that is what it mostly meters — an agent
    resends its whole conversation every turn, so a session ending on a 60k
    context has spent roughly 60k on each of its late turns rather than once."""
    allowed_cidrs: list[str] = Field(default_factory=list)
    expires_at: UtcDatetime
    """Mandatory, with no "never" option, so that rotation is forced rather
    than encouraged."""

    default_capability: str | None = Field(default=None, max_length=64)
    """Optional, and omitting it is the ordinary case: a capability this key was
    not issued for is refused.

    Not an enum here, because the check that matters is not "is this a
    capability" but "is this one of *this key's* capabilities", which only the
    use case holds. Naming something outside `scopes` is a 409 that says which
    list it had to be in.
    """


class UpdateApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    scopes: list[str] | None = Field(default=None, min_length=1)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100_000)
    quota_tokens_per_day: int | None = Field(default=None, ge=1)
    allowed_cidrs: list[str] | None = None
    expires_at: UtcDatetime | None = None

    default_capability: str | None = Field(default=None, max_length=64)
    """The one field on this model where `null` is a value rather than silence.

    Every other field here reads `None` as "not mentioned, leave it alone",
    which works because none of them has a meaningful null. This one does —
    null is "refuse, as before" — so absent and null have to stay apart, and
    the router tells them apart with `model_fields_set` rather than by their
    value. Without that, a default could be set and never cleared.
    """


class AdminErrorResponse(BaseModel):
    """The shape every admin error actually has, declared so the document says so.

    FastAPI advertises `HTTPValidationError` — its own `{"detail": [...]}` — for
    the 422 on every route with a body. Since `_admin_validation_handler` that
    has been false: the handler returns this instead, and the generated frontend
    types were documenting a body the server does not send. In a change whose
    point was making backend/frontend drift a compile error, the one response
    that provably drifted was the one nothing could check, because it lives in
    the document rather than in a schema anybody wrote.

    Declared on the admin apps for 422 only. The other statuses carry this same
    shape and remain undocumented, which is a smaller gap of the same kind: they
    are raised from `DomainError` rather than from a route signature, so
    enumerating them per route would be a list to maintain by hand and go stale.
    """

    code: str
    """Stable identifier a caller may branch on, e.g. `invalid_request`."""

    message: str
    """Safe to show a person. Never carries internal detail (security.md §5)."""

    request_id: str | None = None
    """Matches the `X-Request-Id` header, for quoting into a bug report."""


class IssuedApiKeyResponse(BaseModel):
    key: ApiKeyResponse
    plaintext: str
    """Present in this response and in no other, ever."""
