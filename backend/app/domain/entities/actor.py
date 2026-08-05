"""Who is making a request.

`Actor` unifies the three authentication sources (Tailscale identity, a local
session, an API key) into one shape, so that authorization logic in the use
case layer does not branch on how the caller arrived.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.domain.entities.tenant import DEFAULT_TENANT_ID

ActorSource = Literal["tailnet", "local", "api_key", "dev"]


class Role(StrEnum):
    """Who someone is, from which their scopes are derived.

    Not a ladder. `curator` may write knowledge that `operator` may not touch,
    and `operator` may restart a node that `tenant_admin` may not — so these do
    not nest and no comparison between them is meaningful. The one ordering
    that holds is that `admin` holds every scope and the rest hold subsets.

    The tenant boundary is *not* one of these. It is enforced structurally by
    repository construction (`di.py` builds `ManageUsers` with a tenant-scoped
    user repository), so every role below is already confined to its own
    tenant's users, keys, usage and knowledge whatever its scopes say. That is
    why `tenant_admin` is an ordinary member of this enum rather than a second
    dimension: the only powers that reach across tenants are the platform-global
    ones — tenants, nodes, models and routing policies — and it simply lacks
    the write scopes for them.
    """

    ADMIN = "admin"
    """Platform administrator. Every scope, including the ones that reach
    across tenants."""

    TENANT_ADMIN = "tenant_admin"
    """Everything within one tenant: its people, its keys, its knowledge. Reads
    the fleet, cannot change it, and cannot create a tenant."""

    OPERATOR = "operator"
    """Runs the fleet — models, nodes, routing — and cannot grant anybody
    access. This is the split that matters most: operating a platform and
    deciding who may reach it are different jobs, and fusing them is how an
    operator becomes an administrator without anyone deciding that."""

    CURATOR = "curator"
    """Maintains the knowledge base and nothing else. Named separately because
    §7.3 treats knowledge documents as a prompt-injection surface: whoever
    writes them has real influence over what the models answer, which is a
    permission worth granting deliberately rather than as a side effect of
    being an administrator."""

    AUDITOR = "auditor"
    """Reads everything, changes nothing."""

    USER = "user"
    """Uses the chat UI and manages their own keys."""

    SERVICE = "service"
    """An API key, never a person."""


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

    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"

    USAGE_READ_OWN = "usage:read_own"
    USAGE_READ_ALL = "usage:read_all"

    LOGS_READ = "logs:read"

    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"

    PROMPT_READ = "prompt:read"
    """List the tenant's prompt templates and see what each contains.

    In the base scopes, unlike `knowledge:read`, because selecting a template
    is an ordinary part of asking a question: a member who may use the chat has
    to be able to see which templates exist in order to choose one. What they
    see is text their own tenant's operator wrote.
    """

    PROMPT_WRITE = "prompt:write"
    """Author a template, which is authority over what a model is told before
    it reads anybody's question — so it is content authorship, not fleet
    operation, and it goes to the roles that already hold the knowledge base
    rather than to the one that runs the nodes."""

    RETENTION_WRITE = "retention:write"
    """Set how long records are kept, and delete them ahead of that.

    One scope for reading the policy and for acting on it, because there is no
    audience for the first without the second: the number is only interesting
    to whoever can change it. Admin-only, and the reason is the same one that
    makes `tenant:write` admin-only — it has no smaller sensible holder. A
    tenant administrator who could purge would be able to remove the record of
    what they did inside their own tenant, which is the one boundary the audit
    log exists to see across."""


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

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes

    def may_use(self, capability: str) -> bool:
        """None is unrestricted; a set is exhaustive."""
        if self.allowed_capabilities is None:
            return True
        return capability in self.allowed_capabilities
