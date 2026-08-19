"""Where a refused caller can read their own refusal back.

**The evening this exists for is 2026-08-17.** A `413` said only that the
conversation was too long — no size, no ceiling, no hint that a new conversation
would be refused identically — and the operator opened three of them. A `409` on
an API key's expiry said "The model is not in a state that allows this
operation", because the reason sat in `detail` and `detail` does not leave the
process; it was sent seven times in three minutes and read as the capability
edit beside it having failed. Both messages have since been fixed, and neither
fix helps the next error nobody has thought about.

What these pin is the part that generalises: a refusal is stored, it is stored
as what the caller was told rather than as what the operator would see, and the
person who provoked it can read it without an administrator opening a container
log.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.read_refusals import ReadRefusals
from app.domain.entities.actor import Actor, Role
from app.domain.entities.refusal import Refusal
from app.domain.exceptions import (
    ContextTooLongError,
)
from app.interfaces.http.errors import install_error_handlers
from app.interfaces.http.request_actor import remember_actor
from app.interfaces.http.request_context import RequestContextMiddleware
from tests.unit.fakes import FakeAudit

NOW = datetime(2026, 8, 18, 0, 30, tzinfo=UTC)

AUTHZ = RoleAuthorization()


def _actor(*, role: Role = Role.USER, actor_id: str = "u1", key: str | None = None) -> Actor:
    return Actor(
        id=actor_id,
        display=f"{actor_id}@example.test",
        role=role,
        source="local",
        scopes=AUTHZ.scopes_for(role.value),
        api_key_id=key,
    )


def _refusal(
    *,
    actor_id: str = "u1",
    actor_display: str = "someone@example.test",
    code: str = "context_too_long",
    at: datetime = NOW,
    figures: dict[str, object] | None = None,
) -> Refusal:
    return Refusal(
        id=f"{actor_id}-{code}-{at.isoformat()}",
        at=at,
        code=code,
        status=413,
        actor_id=actor_id,
        actor_display=actor_display,
        api_key_id=None,
        surface="gateway",
        method="POST",
        path="/v1/chat/completions",
        request_id="req_abc",
        message="This input is 140,059 tokens against a limit of 122,880.",
        figures=figures or {},
    )


class FakeRefusals:
    """Rows in memory, filtered the way the repository filters them."""

    def __init__(self, rows: list[Refusal] | None = None) -> None:
        self.rows = list(rows or [])

    def _match(self, row: Refusal, **f: object) -> bool:
        if f.get("actor_id") and row.actor_id != f["actor_id"]:
            return False
        display = f.get("actor_display")
        if isinstance(display, str) and display:
            # A substring, case-insensitively, which is what the repository's
            # `ILIKE '%needle%'` does. Matching exactly here would let a test
            # pass against a fake stricter than the thing it stands for.
            if display.casefold() not in row.actor_display.casefold():
                return False
        if f.get("api_key_id") and row.api_key_id != f["api_key_id"]:
            return False
        if f.get("code") and row.code != f["code"]:
            return False
        if f.get("request_id") and row.request_id != f["request_id"]:
            return False
        since, until = f.get("since"), f.get("until")
        if isinstance(since, datetime) and row.at < since:
            return False
        return not (isinstance(until, datetime) and row.at >= until)

    async def list_refusals(self, *, limit: int, offset: int, **f: object) -> list[Refusal]:
        matched = sorted(
            (r for r in self.rows if self._match(r, **f)), key=lambda r: r.at, reverse=True
        )
        return matched[offset : offset + limit]

    async def count_refusals(self, **f: object) -> int:
        return len([r for r in self.rows if self._match(r, **f)])


def _use_case(rows: list[Refusal]) -> tuple[ReadRefusals, FakeAudit]:
    trail = FakeAudit()
    return ReadRefusals(refusals=FakeRefusals(rows), authz=AUTHZ, audit=trail), trail


class RecordingWriter:
    def __init__(self) -> None:
        self.rows: list[Refusal] = []

    async def record(self, refusal: Refusal) -> None:
        self.rows.append(refusal)


def _app(*, identify: Actor | None) -> tuple[FastAPI, RecordingWriter]:
    app = FastAPI()
    writer = RecordingWriter()
    install_error_handlers(app, envelope="openai", surface="gateway")
    app.add_middleware(RequestContextMiddleware)
    app.state.refusals = writer

    @app.get("/v1/models/{model_id}")
    async def refuses(model_id: str, request: Request) -> None:
        if identify is not None:
            remember_actor(request, identify)
        raise ContextTooLongError(
            detail="operator-facing", estimated=140_059, limit=122_880, basis="tokenizer"
        )

    @app.get("/v1/explodes")
    async def explodes(request: Request) -> None:
        if identify is not None:
            remember_actor(request, identify)
        raise RuntimeError("a wiring mistake")

    return app, writer
