"""Authorization-port implementation over the immutable domain catalog."""

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.actor.catalog import (
    _BY_ROLE,
    ADMIN_ONLY_SCOPES,
    ASSIGNABLE_ROLES,
    ROLE_SCOPES,
)
from app.domain.exceptions import NotAuthorizedError


class RoleAuthorization:
    def require(self, actor: Actor, scope: Scope) -> None:
        if scope not in actor.scopes:
            # The detail names the scope for the operator; the response body
            # does not, and does not reveal whether the target resource exists.
            raise NotAuthorizedError(detail=f"{actor.display} lacks {scope.value}")

    def scopes_for(self, actor_role: str) -> frozenset[Scope]:
        return _BY_ROLE.get(Role(actor_role), frozenset())


__all__ = ["ADMIN_ONLY_SCOPES", "ASSIGNABLE_ROLES", "ROLE_SCOPES", "RoleAuthorization"]
