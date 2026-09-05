"""Actor principal definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.entities.tenant import DEFAULT_TENANT_ID

from .role import Role
from .scope import Scope

ActorSource = Literal["tailnet", "local", "api_key", "dev"]


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    display: str
    """Login or API key id. Safe to write to logs; never a secret."""

    role: Role
    source: ActorSource
    scopes: frozenset[Scope]

    tenant_id: str = DEFAULT_TENANT_ID
    """The tenant this caller acts within. From `users.tenant_id` on the admin
    entrances and `api_keys.tenant_id` on the gateway. The tenant-scoped
    repositories are constructed with it, so a use case reads and writes only
    this tenant's rows. Defaulted so the many test actors that predate tenancy
    keep constructing. See docs/architecture/security.md section 7.3."""

    api_key_id: str | None = None
    """The `key_id` handle when `source` is `api_key`, otherwise None.

    Carried explicitly rather than read back out of `display`, because usage
    accounting and the per-key quota both key on it and a positional
    convention would be silently wrong the first time `display` changed.
    """

    allowed_capabilities: frozenset[str] | None = None
    """Which capabilities this credential may invoke. `None` is unrestricted;
    an empty set permits nothing.

    `None` belongs to a person on an admin entrance, whose reach is decided by
    `scopes` alone. A set belongs to an API key and is the list it was issued
    with. The two ends are worth stating explicitly because they read alike and
    mean opposite things: `may_use` returns True for `None` and False for
    every capability when the set is empty.

    Separate from `scopes` because the two answer different questions.
    `Scope.CHAT_USE` answers "may this caller reach inference at all", and it
    is drawn from a hardcoded table so no database row can widen it. Which
    *capability* is then asked for is data, chosen per request, and it has no
    scope of its own — mapping capabilities onto scopes one-for-one would put
    the stored list back in charge of the permission set, which §4.2 exists to
    prevent. So the list travels here and is checked where the capability is
    read. Empty means the key may reach nothing, which is what a key issued
    with no capabilities should be.
    """

    default_capability: str | None = None
    """The capability to serve when the one asked for is not in
    `allowed_capabilities`, or None to refuse.

    From `api_keys.default_capability`, and meaningful only alongside a set:
    an admin-entrance person carries `allowed_capabilities=None`, is already
    unrestricted, and never reaches the substitution. `capability_for` is the
    one reader, and it re-checks the value against the set rather than trusting
    it — the issuing use case constrains the pair, and this is what holds if a
    row is written by some other hand.
    """

    compaction_enabled: bool = True
    """Whether this credential's requests are compacted when oversized.

    From `api_keys.compaction_enabled`. True by default, matching the column
    default: a person on an admin entrance and any actor built before the
    field existed gets compaction, and a key that sets it to False gets
    refusal on the original path.
    """

    debug_logging_until: datetime | None = None
    """When this credential's debug window closes, or None when it is shut.

    The same `debug_logging_until` that sits on the API key and the user row,
    carried here so the application layer can read it. It already had one
    consumer — `interfaces/http/request_context`, which decides whether an
    error envelope may carry `detail` — and that one reads it from an ambient
    contextvar set by the resolvers. Full prompt logging cannot: it is decided
    inside `RouteChatRequest`, in the application layer, and reaching from
    there into `interfaces/http` would invert the dependency the hexagon
    exists to hold.

    So the window travels on the actor, which is the object that already
    answers every other question about what this caller may do. Both the
    identity resolvers and the API-key middleware hold the full row, so the
    cost is one assignment in each and the benefit is a rule that a test can
    exercise with a constructed actor and a fixed clock.

    Defaulted to None so that every actor built before this existed — the many
    in the test suite included — stays closed rather than open. A field whose
    unset value granted disclosure would be the wrong way round.
    """

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes

    def may_use(self, capability: str) -> bool:
        """None is unrestricted; a set is exhaustive."""
        if self.allowed_capabilities is None:
            return True
        return capability in self.allowed_capabilities

    def capability_for(self, requested: str) -> str | None:
        """Which capability actually serves `requested`, or None to refuse.

        Three answers in one function so that the rule has one statement: the
        request is served as asked, served by this credential's declared
        default, or refused. Both callers need the same answer for different
        reasons — the use case to route, the HTTP layer to announce a
        substitution in a response header before the body is committed — and a
        rule about authorization derived twice is how the two come to disagree.

        **The default is re-checked against `allowed_capabilities`, not
        trusted.** `ManageApiKeys` will not store a default outside the key's
        own list, so this can only fire on a row that reached the table some
        other way. It costs a set lookup on a path that is already ending, and
        without it one direct write would turn a convenience into a way to
        reach a capability the key was never issued.
        """
        if self.may_use(requested):
            return requested
        if self.default_capability is not None and self.may_use(self.default_capability):
            return self.default_capability
        return None
