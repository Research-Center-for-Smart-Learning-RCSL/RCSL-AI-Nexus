"""The role catalogue, for the screen that explains the roles.

Served rather than duplicated in the frontend. The picker used to offer role
names and nothing else, so choosing between `operator` and `tenant_admin`
meant knowing the source. Copy could have been written into the UI instead,
and it would have been wrong the first time a scope moved — this is generated
from `ROLE_SCOPES`, the same table `RoleAuthorization` enforces, so the screen
cannot describe a permission the platform does not grant.

Readable by any authenticated caller: it is a hardcoded table, documented in
full in security.md §5.2, and it says nothing about who holds which role.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.adapters.authz.role_authorization import ASSIGNABLE_ROLES, ROLE_SCOPES
from app.domain.entities.actor import Actor
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import RoleResponse

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("")
async def list_roles(
    _: Annotated[Actor, Depends(current_actor)],
) -> list[RoleResponse]:
    """Every role a person can be given, widest first.

    `SERVICE` is absent because `ASSIGNABLE_ROLES` excludes it: it belongs to
    an API key, and offering it here would create an account that
    authenticates as one.
    """
    return [
        RoleResponse(
            role=role.value,
            scopes=sorted(scope.value for scope in ROLE_SCOPES[role]),
        )
        for role in ASSIGNABLE_ROLES
    ]
