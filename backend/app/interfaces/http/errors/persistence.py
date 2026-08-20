"""HTTP persistence boundary."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import Request

from app.domain.entities.audit import AuditAction
from app.domain.entities.refusal import Refusal
from app.domain.exceptions import (
    DomainError,
    NotAuthorizedError,
)
from app.interfaces.http.request_actor import actor_from_request
from app.interfaces.http.request_context import current_request_id

logger = logging.getLogger("app.interfaces.http.errors")


def _log(request: Request, exc: DomainError, status: int) -> None:
    """The operator-facing detail goes to the log, never to the response.

    `request_id` is the same value the caller received in `X-Request-Id` and
    in `error.request_id`, which is what makes this line findable from a
    caller's report. `DomainError`'s docstring promised this correlation from
    the start; until 2026-08-05 nothing implemented it.
    """
    logger.warning(
        "domain_error code=%s status=%s path=%s request_id=%s detail=%s",
        exc.code,
        status,
        request.url.path,
        current_request_id(),
        exc.detail,
    )


async def _audit_refusal(request: Request, exc: NotAuthorizedError) -> None:
    """Record an authorization failure, from the one place none can bypass.

    Section 12 requires these and nothing recorded them until 2026-08-02. The
    handler is the right place precisely because it is not a decision point:
    every `NotAuthorizedError` from every use case arrives here, so a new use
    case cannot forget, and a future path that raises without a `require` is
    still seen. Putting it in `AuthorizationPort.require` would be closer to
    the decision but would make that port async at seventy call sites, and
    would still miss the refusals use cases raise directly — an administrator
    changing their own role, a key that does not exist.

    **The gateway does not audit these, and that is deliberate.** Its database
    account may INSERT into `usage_records` and nothing else (section 6), so a
    row here would fail and be logged as a failure on every data-plane 403.
    Granting it `audit_log` would let a compromised gateway write into the
    record that exists to describe the compromise. Its refusals — a key using a
    capability it was not issued for — stay in the application log, and the
    absence is recorded in section 12 rather than hidden here. In practice the
    gateway has no `audit` on its app state, so this returns early.

    Best-effort by construction: `PostgresAudit.record` already swallows and
    logs its own failures, so a refused request cannot become a 500 because the
    audit write failed.
    """
    audit = getattr(request.app.state, "audit", None)
    actor = actor_from_request(request)
    if audit is None or actor is None:
        return

    await audit.record(
        actor,
        AuditAction.AUTHZ_DENIED,
        # The path, not the resource id: this says what was reached for, and
        # the handler cannot know which path parameter was the subject.
        target=request.url.path,
        outcome="denied",
        # `exc.detail` names the missing scope and is operator-facing; it never
        # reaches the response body. Method included because a read and a write
        # refused on the same path are different attempts.
        detail={"method": request.method, "reason": exc.detail or ""},
    )


def _route_path(request: Request) -> str:
    """The route as declared, not the URL as sent, wherever routing got that far.

    `/admin/api-keys/{key_id}` rather than `/admin/api-keys/68953ceb…`. Two
    reasons, and the second is the one that decided it. A thousand refusals on
    one endpoint group together instead of scattering by id, which is what makes
    "this endpoint has been refusing all afternoon" visible. And a path
    parameter is a value the caller chose: storing the template keeps this table
    to what the platform said rather than what the caller sent.

    The route's own `path` is not the whole path — routers are included under a
    prefix, and what `scope["route"]` carries is the inner route's spelling,
    `/api-keys/{key_id}` for a request to `/admin/api-keys/<id>`. So the prefix
    is taken from the request and the tail from the template, by position.

    **Substituting the parameter values into the path instead does not work,
    and it is worth saying why, because it looks like it does.** The values are
    caller-chosen, so a value that also appears earlier in the path templates
    the wrong segment: `GET /admin/users/admin` with `user_id="admin"` stored
    itself as `/{user_id}/users/admin`, and `key_id="keys"` turned
    `/admin/api-keys/keys` into `/admin/api-{key_id}/keys`. Any caller could
    provoke a row that named neither the route nor their request.

    Falls back to the literal path when nothing matched, which is a refusal
    raised before or during routing — a body over the byte limit, a country
    block, a request to a path that does not exist.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    path = request.url.path
    if not isinstance(template, str) or not template:
        return path
    tail = [segment for segment in template.split("/") if segment]
    sent = [segment for segment in path.split("/") if segment]
    if len(sent) < len(tail):
        # Nothing sensible to align; the literal path is still true.
        return path
    return "/" + "/".join([*sent[: len(sent) - len(tail)], *tail])


async def _record_refusal(
    request: Request,
    *,
    code: str,
    status: int,
    message: str,
    figures: dict[str, object],
    surface: str,
) -> None:
    """Keep the refusal where the caller who provoked it can read it back.

    **The handler is the write point, and that is a departure from the shape
    this feature was specified in.** The plan was a row written in the same
    `finally` that records usage, so that one write point served all three
    entrances the way `prompt_logs` does. That works for the inference path and
    only for it: the `409` that cost an operator an evening on 2026-08-17 was an
    API key's expiry being refused on the admin surface, which never reaches
    `RouteChatRequest` at all. Storing every `DomainError` means writing from
    the one place every `DomainError` already passes through, and this is it.

    **Only refusals with an identified caller are kept.** The feature exists so
    that a caller can read their own; an anonymous refusal has no such reader,
    and it would be a row written at whatever rate an unauthenticated client
    chooses to provoke one. The identity-plane refusals that matter — a failed
    sign-in, an authorization denial, a recovery code replayed — are already
    recorded in `audit_log` by §12, which is the table for events about who
    somebody is rather than about what they sent.

    Best-effort twice over: the writer swallows its own failures, and this
    returns quietly when no writer is wired. A deployment that has not run the
    migration still answers its callers.
    """
    writer = getattr(request.app.state, "refusals", None)
    actor = actor_from_request(request)
    if writer is None or actor is None:
        return
    await writer.record(
        Refusal(
            id=str(uuid.uuid4()),
            at=datetime.now(UTC),
            code=code,
            status=status,
            actor_id=actor.id,
            actor_display=actor.display,
            api_key_id=actor.api_key_id,
            surface=surface,
            method=request.method,
            path=_route_path(request),
            request_id=current_request_id(),
            message=message,
            figures=figures,
            tenant_id=actor.tenant_id,
        )
    )
