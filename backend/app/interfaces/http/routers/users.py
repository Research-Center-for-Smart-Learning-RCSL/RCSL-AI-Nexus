"""User accounts, as far as the authentication work needs them.

**Partial on purpose.** Creating an account, listing accounts, and issuing the
two kinds of link are here because they are the other half of the invitation
and reset flows: without them nobody can reach the public entrance at all.
Role changes, disabling, and deletion belong with the rest of the admin API
and are not implemented yet; `docs/ROADMAP.md` carries what is outstanding.

Authorization is not enforced here. Each use case declares the scope it
requires and checks it, so a second caller reaching the same use case from
somewhere else cannot skip the check by not knowing about it.
See docs/architecture/backend.md section 7.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends

from app.adapters.persistence.repositories import PostgresUserRepository
from app.application.use_cases.issue_invitation import IssuedInvitation, IssueInvitation
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.invitation import InvitationPurpose
from app.domain.exceptions import NotAuthorizedError
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import build_issue_invitation, get_user_repository
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateUserRequest,
    CreateUserResponse,
    InvitationResponse,
    UserResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

ONBOARD_PATH = "/accept-invite"
RESET_PATH = "/reset-password"


@router.get("")
async def list_users(
    actor: Annotated[Actor, Depends(current_actor)],
    users: Annotated[PostgresUserRepository, Depends(get_user_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[UserResponse]:
    _require(actor, Scope.USER_READ)
    return [UserResponse.of(user) for user in await users.list_all()]


@router.post("", status_code=201)
async def create_user(
    payload: CreateUserRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    invitations: Annotated[IssueInvitation, Depends(build_issue_invitation)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreateUserResponse:
    """Creates the account and issues its first link in one call.

    The link is in this response and in no other. Only the token's hash is
    stored, so an administrator who closes the dialog has to reissue rather
    than look it up.
    """
    issued = await invitations.create_account(
        actor,
        login=str(payload.login),
        display_name=payload.display_name,
        role=payload.role,
    )
    return CreateUserResponse(
        user=UserResponse.of(issued.user),
        invitation=_invitation_response(issued, settings),
    )


@router.post("/{user_id}/invitations", status_code=201)
async def reissue_invitation(
    user_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    invitations: Annotated[IssueInvitation, Depends(build_issue_invitation)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvitationResponse:
    issued = await invitations.reissue_onboarding(actor, user_id=user_id)
    return _invitation_response(issued, settings)


@router.post("/{user_id}/password-reset", status_code=201)
async def issue_password_reset(
    user_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    invitations: Annotated[IssueInvitation, Depends(build_issue_invitation)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvitationResponse:
    issued = await invitations.issue_password_reset(actor, user_id=user_id)
    return _invitation_response(issued, settings)


def _require(actor: Actor, scope: Scope) -> None:
    """The listing has no use case of its own yet.

    Written as an explicit check rather than omitted, so that adding the use
    case later moves this check rather than introducing one that was never
    there.
    """
    if not actor.has(scope):
        raise NotAuthorizedError(detail=f"{actor.display} lacks {scope.value}")


def _invitation_response(issued: IssuedInvitation, settings: Settings) -> InvitationResponse:
    path = ONBOARD_PATH if issued.purpose == InvitationPurpose.ONBOARD else RESET_PATH
    url = f"{settings.admin_base_url.rstrip('/')}{path}?token={quote(issued.token)}"

    return InvitationResponse(
        id=issued.invitation_id,
        user_id=issued.user.id,
        url=url,
        expires_at=issued.expires_at,
    )
