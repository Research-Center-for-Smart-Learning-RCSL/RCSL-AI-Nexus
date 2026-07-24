"""Redeeming a link. Every route here is unauthenticated by design.

The token *is* the credential, so these run before any session exists. They
are still fronted by the perimeter middleware — the trusted-proxy check and
the country filter — and by CSRF, and every failure returns the same error,
so the endpoints cannot be used to enumerate which links were ever issued.

The token arrives in the query string on the two GETs, which is a deliberate
compromise: the alternative is a POST the browser cannot make from a link
someone clicked. It is mitigated by the token being single use, short lived,
and stored only as a hash.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.application.use_cases.accept_invitation import AcceptInvitation
from app.infrastructure.di import build_accept_invitation
from app.interfaces.http.qr import provisioning_qr_response
from app.interfaces.http.schemas.admin_schemas import (
    AcceptInvitationRequest,
    ConsumeResetRequest,
    EnrolmentResponse,
    RecoveryCodesResponse,
    ResetTargetResponse,
)

router = APIRouter(tags=["invitations"])

TokenQuery = Annotated[str, Query(min_length=1, max_length=256)]


@router.get("/invitations")
async def read_invitation(
    token: TokenQuery,
    invitations: Annotated[AcceptInvitation, Depends(build_accept_invitation)],
) -> EnrolmentResponse:
    """Validate the link and return what the enrolment screen needs.

    Called before the form renders, so a consumed or expired link fails
    immediately rather than after the recipient has chosen a password.
    """
    enrolment = await invitations.begin(token)
    return EnrolmentResponse(
        provisioning_uri=enrolment.provisioning_uri,
        secret=enrolment.secret,
        login=enrolment.login,
    )


@router.get("/invitations/totp-qr")
async def invitation_totp_qr(
    token: TokenQuery,
    invitations: Annotated[AcceptInvitation, Depends(build_accept_invitation)],
) -> Response:
    """The same enrolment, rendered as an image.

    `begin` is idempotent while the candidate secret is held, so this shows
    the same secret the form is displaying rather than issuing a second one.
    """
    return provisioning_qr_response((await invitations.begin(token)).provisioning_uri)


@router.post("/invitations/accept")
async def accept_invitation(
    payload: AcceptInvitationRequest,
    invitations: Annotated[AcceptInvitation, Depends(build_accept_invitation)],
) -> RecoveryCodesResponse:
    codes = await invitations.complete(payload.token, payload.password, payload.totp_code)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.get("/password-resets")
async def read_password_reset(
    token: TokenQuery,
    invitations: Annotated[AcceptInvitation, Depends(build_accept_invitation)],
) -> ResetTargetResponse:
    """Only the login. Whoever holds the link has not proved they are that
    person yet, so nothing else about the account is returned."""
    return ResetTargetResponse(login=await invitations.describe_reset(token))


@router.post("/password-resets/consume", status_code=204)
async def consume_password_reset(
    payload: ConsumeResetRequest,
    invitations: Annotated[AcceptInvitation, Depends(build_accept_invitation)],
) -> Response:
    await invitations.consume_reset(payload.token, payload.password)
    return Response(status_code=204)
