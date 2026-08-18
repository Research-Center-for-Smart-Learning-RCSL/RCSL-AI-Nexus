"""API key entity.

The digest is an HMAC over the plaintext with a server-side pepper, not a
slow KDF: the key is a 256-bit random value so brute force is infeasible
regardless of hash speed, and this verification sits on the gateway's hot
path where bcrypt would cost roughly 100ms per request.

`key_id` is an independent random lookup handle, deliberately not a prefix of
the secret, so nothing secret ends up in logs or indexes.
See docs/architecture/security.md section 4.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import IPv4Network, IPv6Network

from app.domain.entities.tenant import DEFAULT_TENANT_ID

KEY_PREFIX = "nx_live_"


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: str
    key_id: str
    digest: str
    name: str
    owner_id: str

    expires_at: datetime
    """No default and NOT NULL in the schema. Optionality here previously meant
    a key with no expiry was treated as never expiring, so the mandatory
    rotation the design relies on could be bypassed by one direct write.
    Placed among the required fields so that omitting it is a type error."""

    tenant_id: str = DEFAULT_TENANT_ID
    """The tenant this key belongs to, carried into the `Actor` the gateway
    builds so a key can only ever reach its own tenant's data. Defaulted for the
    same reason `User.tenant_id` is; the issuing use case and the scoped
    repository set it."""

    scopes: frozenset[str] = field(default_factory=frozenset)
    allowed_cidrs: tuple[IPv4Network | IPv6Network, ...] = ()
    """Empty means unrestricted. Defends against key leakage specifically:
    a key committed to a public repository is unusable from elsewhere."""

    rate_limit_rpm: int = 60
    quota_tokens_per_day: int | None = None

    default_capability: str | None = None
    """What to serve when a caller names a capability this key was not issued
    for, or `None` to refuse — which is the default and remains the behaviour
    of every key that does not set it.

    **Opt-in, per key, because the refusal is worth more than the convenience
    to almost everybody.** `model` taking a capability rather than a model name
    is this platform's one real divergence, and `capability_not_issued` is the
    only channel that tells an integrator their client overrode the model line
    they configured — Codex's own picker does exactly that, and the refusal is
    how three separate integrations found out. A platform-wide fallback would
    have bought convenience by making that misconfiguration permanent and
    invisible. Set here, it is the issuer's explicit choice for one key, it is
    visible in the key's own settings, and it can be withdrawn.

    Constrained to a capability the key already holds, at issue and again at
    use. It is a substitution, never a widening: a key issued `chat` can be
    defaulted to `chat` and to nothing else, so the field can shorten the path
    to what the key may already reach and can never add to it.
    """

    created_at: datetime | None = None
    """Assigned by the database on first write. `None` means "not persisted
    yet", which is why it is not required at construction.

    There is no `last_used_at` beside it. Keeping one current would mean the
    gateway writing to `api_keys` on every request, which the account split in
    security.md section 6 exists to prevent; the same fact is derived from
    `usage_records`."""

    revoked_at: datetime | None = None
    debug_logging_until: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at > now
