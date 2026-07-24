"""User accounts.

Authorization is not enforced here. Each use case declares the scope it
requires and checks it, so a second caller reaching the same use case from
somewhere else cannot skip the check by not knowing about it.
See docs/architecture/backend.md section 7.

`PATCH` carries `disabled` alongside the editable fields because the frontend
sends one form. It routes to a different use-case method, since disabling has
consequences a rename does not: every live session for that account ends
immediately rather than at its own expiry.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response

from app.application.use_cases.issue_invitation import IssuedInvitation, IssueInvitation
from app.application.use_cases.manage_users import ManageUsers
from app.domain.entities.actor import Actor
from app.domain.entities.invitation import InvitationPurpose
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import build_issue_invitation, build_manage_users
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import (
    CreateUserRequest,
    CreateUserResponse,
    InvitationResponse,
    UpdateUserRequest,
    UserResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

ONBOARD_PATH = "/accept-invite"
RESET_PATH = "/reset-password"


@router.get("")
async def list_users(
    actor: Annotated[Actor, Depends(current_actor)],
    users: Annotated[ManageUsers, Depends(build_manage_users)],
) -> list[UserResponse]:
    return [UserResponse.of(user) for user in await users.list_all(actor)]


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


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    users: Annotated[ManageUsers, Depends(build_manage_users)],
) -> UserResponse:
    user = await users.update(actor, user_id, display_name=payload.display_name, role=payload.role)
    if payload.disabled is not None:
        user = await users.set_disabled(actor, user_id, disabled=payload.disabled)
    return UserResponse.of(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    actor: Annotated[Actor, Depends(current_actor)],
    users: Annotated[ManageUsers, Depends(build_manage_users)],
) -> Response:
    """Removes the account and everything holding a foreign key to it, so
    their API keys stop working at the same moment. Usage and audit rows keep
    the id as a plain column and survive, which is what makes the trail worth
    having."""
    await users.delete(actor, user_id)
    return Response(status_code=204)


def _invitation_response(issued: IssuedInvitation, settings: Settings) -> InvitationResponse:
    path = ONBOARD_PATH if issued.purpose == InvitationPurpose.ONBOARD else RESET_PATH
    url = f"{settings.admin_base_url.rstrip('/')}{path}?token={quote(issued.token)}"

    return InvitationResponse(
        id=issued.invitation_id,
        user_id=issued.user.id,
        url=url,
        expires_at=issued.expires_at,
    )
