"""The signed-in user's own account.

`GET /me` is the first call the frontend makes and the one everything else
waits on: it carries the entrance's `auth_mode`, which decides what a 401
means everywhere else in the UI.

Every route here acts on `actor.id`. None of them takes a user identifier,
so there is no path by which a caller could aim one at somebody else.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.adapters.persistence.repositories import PostgresUserRepository
from app.adapters.session.session_store import SessionData
from app.application.use_cases.manage_own_account import ManageOwnAccount
from app.domain.entities.actor import Actor
from app.domain.exceptions import NotAuthenticatedError
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import build_manage_own_account, get_user_repository
from app.interfaces.http.middleware.identity import current_actor, current_session
from app.interfaces.http.qr import provisioning_qr_response
from app.interfaces.http.schemas.admin_schemas import (
    BeginTotpRequest,
    ChangePasswordRequest,
    ConfirmTotpRequest,
    EnrolmentResponse,
    MeResponse,
    RecoveryCodesResponse,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def read_me(
    actor: Annotated[Actor, Depends(current_actor)],
    session: Annotated[SessionData | None, Depends(current_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[PostgresUserRepository, Depends(get_user_repository)],
) -> MeResponse:
    # Read back rather than answered from the actor: `Actor.display` is the
    # login, and the UI wants the name a person chose. The actor deliberately
    # carries only what authorization needs.
    user = await users.get(actor.id)
    if user is None:
        raise NotAuthenticatedError(detail=f"actor {actor.id} has no user row")

    return MeResponse(
        id=user.id,
        # The entrance this request actually arrived through, not the
        # deployment-wide setting. `settings.auth_mode` reads `tailnet` in any
        # real deployment, so the public entrance answered `tailnet` here even
        # after the 401 envelope was fixed to say `local` — and the UI prefers
        # this field over the 401 hint, so a signed-in user on the public
        # entrance lost the Account button, Sign out, the password form and
        # TOTP re-enrolment, on the only entrance that has any of them.
        #
        # `actor.source` is set by whichever resolver authenticated the
        # request: `local` for a session, `tailnet` (or `dev`) for the header.
        # It cannot disagree with how the caller got here.
        auth_mode=actor.source,
        login=user.login,
        display_name=user.display_name,
        role=user.role.value,
        # From the actor, not re-derived from `user.role`: the actor's scopes
        # are what the request was actually authorized with, so the UI is told
        # the same thing the server will enforce.
        scopes=sorted(scope.value for scope in actor.scopes),
        session_expires_at=session.expires_at if session else None,
    )


@router.post("/password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    session: Annotated[SessionData | None, Depends(current_session)],
    accounts: Annotated[ManageOwnAccount, Depends(build_manage_own_account)],
) -> Response:
    await accounts.change_password(
        actor,
        # Empty on the tailnet entrance, which holds no session. The effect is
        # that every session on the public entrance is invalidated with none
        # kept, which is the right outcome: there is no local session here to
        # preserve.
        session_id=session.session_id if session else "",
        current_password=payload.current_password,
        new_password=payload.password,
    )
    return Response(status_code=204)


@router.post("/totp")
async def begin_totp_reenrolment(
    payload: BeginTotpRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    accounts: Annotated[ManageOwnAccount, Depends(build_manage_own_account)],
) -> EnrolmentResponse:
    enrolment = await accounts.begin_totp_reenrolment(
        actor, current_password=payload.current_password
    )
    return EnrolmentResponse(
        provisioning_uri=enrolment.provisioning_uri,
        secret=enrolment.secret,
        login=enrolment.login,
    )


@router.get("/totp/qr")
async def totp_qr(
    actor: Annotated[Actor, Depends(current_actor)],
    accounts: Annotated[ManageOwnAccount, Depends(build_manage_own_account)],
) -> Response:
    return provisioning_qr_response(await accounts.pending_provisioning_uri(actor))


@router.post("/totp/confirm")
async def confirm_totp_reenrolment(
    payload: ConfirmTotpRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    session: Annotated[SessionData | None, Depends(current_session)],
    accounts: Annotated[ManageOwnAccount, Depends(build_manage_own_account)],
) -> RecoveryCodesResponse:
    codes = await accounts.confirm_totp_reenrolment(
        actor,
        session_id=session.session_id if session else "",
        code=payload.code,
    )
    return RecoveryCodesResponse(recovery_codes=codes)
