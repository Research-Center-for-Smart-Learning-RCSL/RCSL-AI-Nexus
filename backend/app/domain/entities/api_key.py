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

KEY_PREFIX = "nx_live_"


@dataclass(frozen=True, slots=True)
class ApiKey:
    id: str
    key_id: str
    digest: str
    name: str
    owner_id: str

    scopes: frozenset[str] = field(default_factory=frozenset)
    allowed_cidrs: tuple[IPv4Network | IPv6Network, ...] = ()
    """Empty means unrestricted. Defends against key leakage specifically:
    a key committed to a public repository is unusable from elsewhere."""

    rate_limit_rpm: int = 60
    quota_tokens_per_day: int | None = None

    expires_at: datetime | None = None
    """Required in practice; the create use case refuses a null expiry."""

    revoked_at: datetime | None = None
    debug_logging_until: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        if self.revoked_at is not None:
            return False
        return not (self.expires_at is not None and self.expires_at <= now)
