"""RFC 6238 TOTP.

`pyotp.TOTP.verify` is not used, because it answers the wrong question. It
returns a boolean, and replay prevention needs to know *which* time counter
matched so the accepted value can be recorded and anything at or below it
refused afterwards. See docs/architecture/security.md section 5.3.
"""

from __future__ import annotations

import time
from hmac import compare_digest

import pyotp

from app.domain.exceptions import InvalidTotpError

STEP_SECONDS = 30
DIGITS = 6

SKEW_STEPS = 1
"""One step either side, so a device whose clock is up to 30 seconds out still
works. Widening this multiplies the window in which an observed code is
useful, which is precisely what the counter check exists to shrink."""

_OFFSETS = tuple(range(-SKEW_STEPS, SKEW_STEPS + 1))


class PyotpTotp:
    def generate_secret(self) -> str:
        return pyotp.random_base32()

    def provisioning_uri(self, secret: str, login: str, issuer: str) -> str:
        return pyotp.TOTP(secret, interval=STEP_SECONDS, digits=DIGITS).provisioning_uri(
            name=login, issuer_name=issuer
        )

    def verify(self, secret: str, code: str, last_counter: int | None) -> int:
        """Return the accepted counter, or raise `InvalidTotpError`."""
        candidate = code.strip().replace(" ", "")
        if len(candidate) != DIGITS or not candidate.isdigit():
            # Rejected before any HMAC work, so a flood of junk costs nothing.
            raise InvalidTotpError(detail="malformed code")

        totp = pyotp.TOTP(secret, interval=STEP_SECONDS, digits=DIGITS)
        now_counter = int(time.time()) // STEP_SECONDS

        matched: int | None = None
        for offset in _OFFSETS:
            counter = now_counter + offset
            expected = totp.at(counter * STEP_SECONDS)
            # Constant time, and every offset is evaluated rather than breaking
            # on the first match, so response timing does not reveal how far
            # the presenting device's clock is from this host's.
            if compare_digest(expected, candidate):
                matched = counter

        if matched is None:
            raise InvalidTotpError(detail="no counter in window matched")

        if last_counter is not None and matched <= last_counter:
            raise InvalidTotpError(detail=f"counter {matched} already used")

        return matched
