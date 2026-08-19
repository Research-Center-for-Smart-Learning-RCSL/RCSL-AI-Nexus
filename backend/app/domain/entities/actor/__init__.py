"""Stable actor facade with explicit role, scope, catalog, and principal exports."""

from .catalog import ADMIN_ONLY_SCOPES, ASSIGNABLE_ROLES, ROLE_SCOPES
from .principal import Actor, ActorSource
from .role import Role
from .scope import Scope

__all__ = [
    "ADMIN_ONLY_SCOPES",
    "ASSIGNABLE_ROLES",
    "ROLE_SCOPES",
    "Actor",
    "ActorSource",
    "Role",
    "Scope",
]
