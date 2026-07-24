"""Who is making a request.

`Actor` unifies the three authentication sources (Tailscale identity, a local
session, an API key) into one shape, so that authorization logic in the use
case layer does not branch on how the caller arrived.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ActorSource = Literal["tailnet", "local", "api_key", "dev"]


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"
    SERVICE = "service"


class Scope(StrEnum):
    """A single permission. Use cases declare the scope they require."""

    CHAT_USE = "chat:use"

    MODEL_READ = "model:read"
    MODEL_WRITE = "model:write"

    ROUTING_READ = "routing:read"
    ROUTING_WRITE = "routing:write"

    API_KEY_READ_OWN = "api_key:read_own"
    API_KEY_WRITE_OWN = "api_key:write_own"
    API_KEY_WRITE_ANY = "api_key:write_any"

    USER_READ = "user:read"
    USER_WRITE = "user:write"

    NODE_READ = "node:read"
    NODE_WRITE = "node:write"

    USAGE_READ_OWN = "usage:read_own"
    USAGE_READ_ALL = "usage:read_all"

    LOGS_READ = "logs:read"


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    display: str
    """Login or API key id. Safe to write to logs; never a secret."""

    role: Role
    source: ActorSource
    scopes: frozenset[Scope]

    api_key_id: str | None = None
    """The `key_id` handle when `source` is `api_key`, otherwise None.

    Carried explicitly rather than read back out of `display`, because usage
    accounting and the per-key quota both key on it and a positional
    convention would be silently wrong the first time `display` changed.
    """

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes
