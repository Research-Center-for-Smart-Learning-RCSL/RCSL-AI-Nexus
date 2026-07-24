"""Server-side sessions, held on `CachePort`.

The cookie carries an opaque identifier and nothing else. Nothing about the
user, their role, or their expiry is signed into the client's copy, so there
is no signature to get wrong and revocation is a delete rather than a
blocklist. See docs/architecture/security.md section 5.3.

**How "changing a password invalidates every other session" is implemented.**
`CachePort` has no key enumeration, and adding one to satisfy this would mean
a per-user index that can drift out of step with the sessions it lists. A
watermark is used instead: `sessions_valid_from:{user_id}` holds an instant,
and a session created strictly before it is dead. Password change writes the
current time there and re-stamps the caller's own session, so every other
session on every other worker dies at once without any of them being listed.

The watermark's TTL is the absolute session lifetime, which is what makes its
expiry safe: by the time it disappears, every session it could have
invalidated has already passed its own absolute expiry.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.ports.infrastructure_ports import CachePort

SESSION_ID_BYTES = 32
CSRF_TOKEN_BYTES = 32

SESSION_KEY_PREFIX = "session:"
WATERMARK_KEY_PREFIX = "sessions_valid_from:"


@dataclass(frozen=True, slots=True)
class SessionData:
    session_id: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    """Absolute expiry, fixed at login. The idle timeout is enforced separately
    by the entry's own TTL, so a session dies at whichever comes first."""

    csrf_token: str


class SessionStore:
    def __init__(self, cache: CachePort, *, absolute_ttl: int, idle_ttl: int) -> None:
        self._cache = cache
        self._absolute_ttl = absolute_ttl
        self._idle_ttl = idle_ttl

    async def create(self, user_id: str, now: datetime) -> SessionData:
        """A fresh identifier every time.

        Sessions are only ever created here, at the end of a successful login,
        and never adopted from a value the client already held. That is what
        makes session fixation impossible rather than merely unlikely.
        """
        data = SessionData(
            session_id=secrets.token_urlsafe(SESSION_ID_BYTES),
            user_id=user_id,
            created_at=now,
            expires_at=datetime.fromtimestamp(now.timestamp() + self._absolute_ttl, UTC),
            csrf_token=secrets.token_urlsafe(CSRF_TOKEN_BYTES),
        )
        await self._write(data, now)
        return data

    async def read(self, session_id: str, now: datetime) -> SessionData | None:
        raw = await self._cache.get(_session_key(session_id))
        if raw is None:
            return None

        data = _decode(session_id, raw)
        if data is None:
            # Unparsable: a format change or a corrupted entry. Treated as
            # absent and removed, rather than raising, so a bad entry logs the
            # user out instead of returning 500 on every subsequent request.
            await self._cache.delete(_session_key(session_id))
            return None

        if now >= data.expires_at:
            await self._cache.delete(_session_key(session_id))
            return None

        if await self._superseded(data):
            await self._cache.delete(_session_key(session_id))
            return None

        # Rewriting extends the idle window. Done on every read, which is what
        # makes the timeout idle rather than fixed.
        await self._write(data, now)
        return data

    async def destroy(self, session_id: str) -> None:
        await self._cache.delete(_session_key(session_id))

    async def invalidate_all(self, user_id: str, now: datetime) -> None:
        """Used when there is no session to preserve: a password reset consumed
        from a link, or an account being disabled."""
        await self._set_watermark(user_id, now)

    async def invalidate_others(self, user_id: str, keep_session_id: str, now: datetime) -> None:
        """Kill every session for this user except the caller's own.

        Order matters. The watermark is written first, so a session being read
        concurrently cannot pass the check against a stale watermark and then
        have its idle window extended past this point.

        The kept session is re-stamped rather than exempted, because an
        exemption would have to live somewhere and would then be a second
        thing to invalidate. Its absolute expiry is deliberately not extended:
        changing a password is not a reason to grant another twelve hours.
        """
        await self._set_watermark(user_id, now)

        raw = await self._cache.get(_session_key(keep_session_id))
        if raw is None:
            return
        kept = _decode(keep_session_id, raw)
        if kept is None or kept.user_id != user_id:
            # Not this user's session. Leaving it to die at the watermark is
            # the safe reading of a mismatch.
            return

        await self._write(
            SessionData(
                session_id=kept.session_id,
                user_id=kept.user_id,
                created_at=now,
                expires_at=kept.expires_at,
                csrf_token=kept.csrf_token,
            ),
            now,
        )

    async def _set_watermark(self, user_id: str, now: datetime) -> None:
        await self._cache.set(
            _watermark_key(user_id),
            str(now.timestamp()),
            ttl_seconds=self._absolute_ttl,
        )

    async def _superseded(self, data: SessionData) -> bool:
        raw = await self._cache.get(_watermark_key(data.user_id))
        if raw is None:
            return False
        try:
            watermark = float(raw)
        except ValueError:
            # Fail closed: an unreadable watermark means an invalidation was
            # requested and cannot be evaluated, and the safe reading of that
            # is that the session is gone.
            return True
        return data.created_at.timestamp() < watermark

    async def _write(self, data: SessionData, now: datetime) -> None:
        remaining = int(data.expires_at.timestamp() - now.timestamp())
        ttl = min(self._idle_ttl, remaining)
        if ttl <= 0:
            await self._cache.delete(_session_key(data.session_id))
            return
        await self._cache.set(_session_key(data.session_id), _encode(data), ttl_seconds=ttl)


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _watermark_key(user_id: str) -> str:
    return f"{WATERMARK_KEY_PREFIX}{user_id}"


def _encode(data: SessionData) -> str:
    return json.dumps(
        {
            "user_id": data.user_id,
            "created_at": data.created_at.timestamp(),
            "expires_at": data.expires_at.timestamp(),
            "csrf": data.csrf_token,
        }
    )


def _decode(session_id: str, raw: str) -> SessionData | None:
    try:
        payload = json.loads(raw)
        return SessionData(
            session_id=session_id,
            user_id=str(payload["user_id"]),
            created_at=datetime.fromtimestamp(float(payload["created_at"]), UTC),
            expires_at=datetime.fromtimestamp(float(payload["expires_at"]), UTC),
            csrf_token=str(payload["csrf"]),
        )
    except (ValueError, TypeError, KeyError):
        return None
