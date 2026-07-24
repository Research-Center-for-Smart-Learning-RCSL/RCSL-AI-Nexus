"""Scope enforcement.

Implements `AuthorizationPort`. Deliberately a hardcoded mapping rather than
a lookup: a compromised database row must not be able to grant itself a scope
it was never issued.
"""

from __future__ import annotations

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.exceptions import NotAuthorizedError

_ADMIN_SCOPES = frozenset(Scope)

_USER_SCOPES = frozenset(
    {
        Scope.CHAT_USE,
        Scope.MODEL_READ,
        Scope.ROUTING_READ,
        Scope.NODE_READ,
        Scope.API_KEY_READ_OWN,
        Scope.API_KEY_WRITE_OWN,
        Scope.USAGE_READ_OWN,
    }
)

_SERVICE_SCOPES = frozenset({Scope.CHAT_USE, Scope.USAGE_READ_OWN})
"""An API key can never hold a control-plane scope, whatever its stored list
says. The stored list narrows this set; it cannot widen it."""

_BY_ROLE: dict[Role, frozenset[Scope]] = {
    Role.ADMIN: _ADMIN_SCOPES,
    Role.USER: _USER_SCOPES,
    Role.SERVICE: _SERVICE_SCOPES,
}


class RoleAuthorization:
    def require(self, actor: Actor, scope: Scope) -> None:
        if scope not in actor.scopes:
            # The detail names the scope for the operator; the response body
            # does not, and does not reveal whether the target resource exists.
            raise NotAuthorizedError(detail=f"{actor.display} lacks {scope.value}")

    def scopes_for(self, actor_role: str) -> frozenset[Scope]:
        return _BY_ROLE.get(Role(actor_role), frozenset())
