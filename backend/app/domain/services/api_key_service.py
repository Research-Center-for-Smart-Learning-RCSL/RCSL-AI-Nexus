"""API key issue and verification.

Token shape:

    nx_live_<key_id>.<secret>

`key_id` travels in the token so that verification is a single indexed lookup
rather than a scan comparing digests row by row. It is an independent random
value, not derived from the secret, so nothing secret ends up in an index, a
log line, or the management UI.

The separator is a dot because `secrets.token_urlsafe` emits `[A-Za-z0-9_-]`
and never a dot, so splitting is unambiguous. Splitting on an underscore would
be, since the secret can contain them.

Digests are HMAC-SHA256 with a server-side pepper rather than a slow KDF. The
key is a 256-bit random value, so brute force is infeasible regardless of hash
speed, and this runs on the gateway's hot path where bcrypt would cost roughly
100 ms per request. See docs/architecture/security.md section 4.2.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

KEY_PREFIX = "nx_live_"
SEPARATOR = "."
KEY_ID_BYTES = 8
SECRET_BYTES = 32


@dataclass(frozen=True, slots=True)
class IssuedKey:
    plaintext: str
    """Shown once, at issue, and never recoverable afterwards."""

    key_id: str
    digest: str


class ApiKeyService:
    def __init__(self, peppers: tuple[bytes, ...]) -> None:
        """Accepts several peppers so rotation can be staged.

        The first is used for new keys; the rest are still accepted on
        verification, which is what lets a pepper change without invalidating
        every key at once.
        """
        if not peppers:
            raise ValueError("at least one pepper is required")
        self._peppers = peppers

    def issue(self) -> IssuedKey:
        key_id = secrets.token_hex(KEY_ID_BYTES)
        secret = secrets.token_urlsafe(SECRET_BYTES)
        plaintext = f"{KEY_PREFIX}{key_id}{SEPARATOR}{secret}"
        return IssuedKey(
            plaintext=plaintext,
            key_id=key_id,
            digest=self._digest(plaintext, self._peppers[0]),
        )

    def parse_key_id(self, plaintext: str) -> str | None:
        """Extract the lookup handle, or None if the token is malformed.

        Returning None rather than raising keeps the caller's failure path
        identical for a malformed token and an unknown one, so neither the
        response nor its timing distinguishes them.
        """
        if not plaintext.startswith(KEY_PREFIX):
            return None
        remainder = plaintext[len(KEY_PREFIX) :]
        key_id, separator, secret = remainder.partition(SEPARATOR)
        if not separator or not key_id or not secret:
            return None
        if len(key_id) != KEY_ID_BYTES * 2 or not all(c in "0123456789abcdef" for c in key_id):
            return None
        return key_id

    def verify(self, plaintext: str, stored_digest: str) -> bool:
        """Constant-time comparison against every accepted pepper."""
        return any(
            hmac.compare_digest(self._digest(plaintext, pepper), stored_digest)
            for pepper in self._peppers
        )

    @staticmethod
    def _digest(plaintext: str, pepper: bytes) -> str:
        return hmac.new(pepper, plaintext.encode(), hashlib.sha256).hexdigest()
