"""One refusal, kept where the caller who provoked it can read it.

**Two people lost an evening each on 2026-08-17 to refusals that were correct,
permanent, and silent about which of several things they had just changed had
caused them.** A `413` said only that the conversation was too long — no size,
no ceiling, no hint that a new conversation would be refused identically — and
the operator opened three of them. A `409` on an API key's expiry said "The
model is not in a state that allows this operation", because that error was the
platform's general conflict and the reason sat in `detail`, which does not leave
the process; it was sent seven times in three minutes and read as the capability
edit beside it failing. Both messages have since been fixed, and **neither fix
helps the next error nobody has thought about**. Nothing stored a refusal at
all: the process logged one and moved on, so "what happened at 19:16?" meant an
administrator reading container logs, which is what happened twice that day.

**What is stored is exactly what the caller was told, and never more.** The
code, the status, the public message, and the caller-facing figures — the same
values the response body carried. Not `detail`, which is operator-facing and
whose absence from responses is the rule three other places in this codebase
turn on. Not the model's alias, which `NoAvailableModelError` and
`ContextTooLongError` are both careful to withhold. A row here is a second copy
of something its subject already received, which is what makes the whole table
safe to show them.

**A refusal is not a transcript**, and the distinction is what separates this
from `prompt_log.py`. That table holds what somebody typed and exists only
while a debug window is open; this one holds no request content at all. What it
does hold is shape — a `composition` says a conversation was 97% one message,
and a month of `413`s says how somebody works — which is why the retention
bound is a ceiling rather than a floor, and why reading somebody else's is a
scope rather than a role.

**Only refusals with an identified caller are kept.** The feature's purpose is
that a caller can read their own, and an anonymous refusal has no such reader:
it would be a row nobody owns, written at whatever rate an unauthenticated
client chooses to provoke it. The identity-plane refusals that matter — a failed
sign-in, an authorization denial, a recovery code replayed — are already
recorded in `audit_log` by §12, which is the table that exists for events about
who somebody is rather than about what they sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities.tenant import DEFAULT_TENANT_ID

MAX_FIGURE_CHARS = 2000
"""How much of one caller-facing figure is kept.

`composition` is the long one and it is bounded by the number of messages in a
conversation, so it has no natural ceiling. Truncating here rather than at the
column, because `audit_log` lost whole rows for months to a value wider than
its column — silently, so that padding a URL suppressed the record of probing
it (PROGRESS.md 2026-08-02). A figure that is cut says so; a row that is lost
says nothing.
"""


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refused request, from the one place every refusal passes through."""

    id: str
    at: datetime

    code: str
    """The stable identifier a caller branches on, e.g. `context_too_long`.

    The column an operator actually filters by. `status` is too coarse — the
    evening this table exists for had two 413s with different causes and two
    409s with nothing in common — and the message is prose that changes when
    somebody rewrites it, as both of those did the same day.
    """

    status: int

    actor_id: str
    actor_display: str
    """The login, or the key handle when the caller came through the gateway.

    Denormalised, like `audit_log`'s, and for the two reasons that table gives
    plus one this table adds. The row has no foreign key and must outlive the
    account it names, so a display resolved by joining would vanish exactly
    when somebody is investigating what a departed account was doing. And a
    reader with `refusal:read_all` is looking at a page of other people's
    refusals: an opaque uuid per row makes "whose 413s are these?" a second
    lookup per row, which is the question that view exists to answer.

    Not a disclosure the reader did not already have — every role granted
    `refusal:read_all` also holds `user:read` — and never shown to a reader
    confined to their own, who sees only their own name.
    """

    api_key_id: str | None
    """Set when the refusal came through the gateway on a key, None when it came
    from a person on an admin entrance. Both cases were on the evening this
    exists for, and they are different searches: "this key's 413s" and "what did
    I just do wrong"."""

    surface: str
    """Which entrance refused, named by the composition root that installed the
    handler rather than derived from the envelope: both admin entrances share an
    envelope and are not the same place to be refused."""

    method: str
    path: str
    """The route, not the resource. A refusal on `PATCH /admin/api-keys/{id}`
    is the operator's 409, and that is what makes the row findable without
    storing anything the caller sent."""

    request_id: str | None
    """The value the caller was handed in `X-Request-Id` and in the body.

    Indexed, because it is the way in: a caller reports a failure by quoting it,
    and this is the table that turns it back into what happened.
    """

    message: str
    """The public message, as sent. Stored rather than recomputed from `code`
    because it is what the caller actually read, and the whole point of the
    table is answering "what were they looking at?" — a message rewritten next
    week must not silently rewrite last week's refusal."""

    figures: dict[str, Any] = field(default_factory=dict)
    """The caller-facing extras that accompanied it: `estimated`, `limit`,
    `composition` and `basis` on a `context_too_long`, `retry_after_seconds` on
    the three that carry it, `available` on a capability refusal, and so on.

    A JSON column rather than columns, because the set differs per code and is
    the part most likely to grow: nine error classes carry a figure today and
    four more are specified to. What must not vary is where they come from —
    `interfaces/http/errors.py` builds this from the same function that builds
    the response body, so a figure a caller was shown and a figure stored here
    cannot disagree.
    """

    tenant_id: str = DEFAULT_TENANT_ID

    def truncated(self) -> Refusal:
        """The same refusal with over-long figures cut, each saying so.

        Applied by the writer rather than by the caller, so that no path can
        store an unbounded value by forgetting to.
        """
        if not self.figures:
            return self
        cut = {
            key: (value[:MAX_FIGURE_CHARS] + "… (truncated)")
            if isinstance(value, str) and len(value) > MAX_FIGURE_CHARS
            else value
            for key, value in self.figures.items()
        }
        return Refusal(
            id=self.id,
            at=self.at,
            code=self.code,
            status=self.status,
            actor_id=self.actor_id,
            actor_display=self.actor_display,
            api_key_id=self.api_key_id,
            surface=self.surface,
            method=self.method,
            path=self.path,
            request_id=self.request_id,
            message=self.message,
            figures=cut,
            tenant_id=self.tenant_id,
        )
