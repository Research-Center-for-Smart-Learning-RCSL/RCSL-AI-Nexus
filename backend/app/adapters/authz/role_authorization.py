"""Scope enforcement.

Implements `AuthorizationPort`. Deliberately a hardcoded mapping rather than
a lookup: a compromised database row must not be able to grant itself a scope
it was never issued.

The tables below are the whole of the authorization model. Nothing else reads
a role to decide what may happen — a use case declares a scope and this
answers. That is what makes adding a role cheap and adding one safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.exceptions import NotAuthorizedError

_BASE_SCOPES = frozenset(
    {
        Scope.CHAT_USE,
        Scope.API_KEY_READ_OWN,
        Scope.API_KEY_WRITE_OWN,
        Scope.USAGE_READ_OWN,
    }
)
"""What having an account at all is worth: use the chat UI, manage your own
API keys, see your own usage. Every human role builds on this except
`auditor`, which drops the one write in it."""

_ADMIN_SCOPES = frozenset(Scope)
"""Everything, including scopes added after this line was written.

Deliberate here and dangerous anywhere else, which is why `test_role_scopes.py`
asserts that every scope reaches some other role too: a scope that lands only
in this set silently narrows every role below it, and nothing would say so."""

_TENANT_ADMIN_SCOPES = _BASE_SCOPES | {
    Scope.USER_READ,
    Scope.USER_WRITE,
    Scope.API_KEY_WRITE_ANY,
    Scope.USAGE_READ_ALL,
    Scope.LOGS_READ,
    Scope.KNOWLEDGE_READ,
    Scope.KNOWLEDGE_WRITE,
    Scope.TENANT_READ,
    Scope.MODEL_READ,
    Scope.ROUTING_READ,
    Scope.NODE_READ,
}
"""Full authority over one tenant's people and content; read-only on the fleet.

The confinement to a single tenant is not in this set and could not be: it
comes from the tenant-scoped repositories `di.py` constructs, which is why
`USER_WRITE` here reaches only this tenant's users. What is withheld is every
platform-global write — `TENANT_WRITE`, `NODE_WRITE`, `MODEL_WRITE`,
`ROUTING_WRITE` — because those are the operations whose blast radius is the
whole installation rather than one tenant of it."""

_OPERATOR_SCOPES = _BASE_SCOPES | {
    Scope.MODEL_READ,
    Scope.MODEL_WRITE,
    Scope.NODE_READ,
    Scope.NODE_WRITE,
    Scope.ROUTING_READ,
    Scope.ROUTING_WRITE,
    Scope.LOGS_READ,
    Scope.USAGE_READ_ALL,
    Scope.KNOWLEDGE_READ,
    Scope.USER_READ,
    Scope.TENANT_READ,
}
"""Runs the fleet, grants nobody anything.

`USER_READ` and `TENANT_READ` are present because diagnosing load means knowing
whose load it is, and both are read-only. `USER_WRITE`, `API_KEY_WRITE_ANY` and
`TENANT_WRITE` are the ones deliberately withheld: an operator who can issue a
key or promote an account can hand themselves every other scope in this file,
so withholding them is what makes this role a role rather than a delay."""

_CURATOR_SCOPES = _BASE_SCOPES | {Scope.KNOWLEDGE_READ, Scope.KNOWLEDGE_WRITE}
"""The knowledge base and nothing else. Separate from the roles above because
§7.3 treats knowledge documents as a prompt-injection surface: whoever writes
them shapes what the models answer, which is authority worth granting on
purpose rather than as a side effect of being an administrator."""

_AUDITOR_SCOPES = frozenset(
    {
        Scope.CHAT_USE,
        Scope.API_KEY_READ_OWN,
        Scope.USAGE_READ_OWN,
        Scope.USAGE_READ_ALL,
        Scope.LOGS_READ,
        Scope.MODEL_READ,
        Scope.ROUTING_READ,
        Scope.NODE_READ,
        Scope.USER_READ,
        Scope.TENANT_READ,
        Scope.KNOWLEDGE_READ,
    }
)
"""Reads everything, writes nothing.

Built from scratch rather than from `_BASE_SCOPES`, because that set contains
`API_KEY_WRITE_OWN` and an auditor who can mint themselves a key can act
through the gateway — the point of the role is that its holder leaves no trace
but a read. `CHAT_USE` is kept deliberately: it changes no configuration, and a
role whose holder cannot ask the assistant a question is one nobody accepts
being put in."""

_USER_SCOPES = _BASE_SCOPES
"""Exactly what §5.2 grants a user: use the chat UI, manage their own API
keys, view their own usage. The read scopes for models, routing and nodes are
deliberately absent — they were granted before and let a `user` enumerate the
whole registry and read the node's tailnet address, which the chat composer
(it names a capability, not a model) never needs."""

_SERVICE_SCOPES = frozenset({Scope.CHAT_USE, Scope.USAGE_READ_OWN})
"""An API key can never hold a control-plane scope, whatever its stored list
says. The stored list narrows this set; it cannot widen it."""

_BY_ROLE: dict[Role, frozenset[Scope]] = {
    Role.ADMIN: _ADMIN_SCOPES,
    Role.TENANT_ADMIN: _TENANT_ADMIN_SCOPES,
    Role.OPERATOR: _OPERATOR_SCOPES,
    Role.CURATOR: _CURATOR_SCOPES,
    Role.AUDITOR: _AUDITOR_SCOPES,
    Role.USER: _USER_SCOPES,
    Role.SERVICE: _SERVICE_SCOPES,
}

ADMIN_ONLY_SCOPES = frozenset({Scope.TENANT_WRITE, Scope.RETENTION_WRITE})
"""Scopes no role but `admin` holds — listed, rather than left to be discovered.

Creating a tenant is the one operation with no smaller holder, because a tenant
is the boundary every other role is confined by: granting the power to draw one
is granting the power to step outside it. Adding to this set is a deliberate
narrowing and belongs in this docstring with its reason. A scope that becomes
admin-only *without* being added here fails `test_role_scopes.py`, which is the
point of writing it down.

`retention:write` joined it on 2026-08-04 for a related reason. It sets how
long records are kept and deletes them ahead of that, including audit entries.
Held by a `tenant_admin` it would let the holder erase the record of what they
did inside the tenant they administer — the audit log's whole value is that it
is written by a wider authority than the one being recorded. The platform
administrator can still erase their own trail; that is the deliberate choice
made when this was designed, and it is recorded in `security.md` §12.1 rather
than mitigated here."""

ROLE_SCOPES: Mapping[Role, frozenset[Scope]] = MappingProxyType(_BY_ROLE)
"""Read-only view for callers that describe the model rather than enforce it —
the `/admin/roles` catalogue the settings UI renders. Exported so the screen
explaining these roles is generated from the same table that grants them, and
cannot drift from it.

Genuinely read-only, via `MappingProxyType`. Binding it straight to `_BY_ROLE`
handed every importer — a router, a test — a reference to the dict this module
enforces from, so a stray `ROLE_SCOPES[role] = ...` would have rewritten live
authorization. For a module whose first line argues that no database row may
grant itself a scope, leaving the table writable from anywhere that imports it
was the wrong shape."""

ASSIGNABLE_ROLES: tuple[Role, ...] = (
    Role.ADMIN,
    Role.TENANT_ADMIN,
    Role.OPERATOR,
    Role.CURATOR,
    Role.AUDITOR,
    Role.USER,
)
"""The roles a person may be given, widest authority first.

`SERVICE` is absent: it belongs to an API key, and offering it in a role picker
would create an account that authenticates as one. These are not a ladder —
`curator` writes knowledge that `operator` cannot touch — so the order is a
presentation choice, not a comparison."""


class RoleAuthorization:
    def require(self, actor: Actor, scope: Scope) -> None:
        if scope not in actor.scopes:
            # The detail names the scope for the operator; the response body
            # does not, and does not reveal whether the target resource exists.
            raise NotAuthorizedError(detail=f"{actor.display} lacks {scope.value}")

    def scopes_for(self, actor_role: str) -> frozenset[Scope]:
        return _BY_ROLE.get(Role(actor_role), frozenset())
