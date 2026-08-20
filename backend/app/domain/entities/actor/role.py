"""Actor role definitions."""

from __future__ import annotations

from enum import StrEnum


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
