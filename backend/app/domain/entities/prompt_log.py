"""One conversation, recorded in full, because somebody opened a window.

This is the record `security.md` §9.2 has described since the first draft and
nothing produced until 2026-08-08. The section's whole shape is a promise about
this entity: **metadata by default, full text never** — unless a named
credential's `debug_logging_until` is in the future, in which case the platform
records what the model actually read and what it actually wrote, keeps it for
markedly less time than anything else, and audits whoever reads it.

**What is recorded is the assembled prompt, not the caller's request.** By the
time `RouteChatRequest` is reached, a prompt template has been prepended and
retrieved knowledge passages have been merged in (`ApplyPromptTemplate` and
`GroundChat` both transform the message list ahead of it). That is deliberate
and it is the point: §9.2's "never logged by default" column names *retrieved
knowledge base passages* alongside message content, and an operator debugging a
grounded answer needs to see the passage the model was given rather than the
question the caller asked. It also means one write point covers three
entrances — `/v1/chat/completions`, `/v1/responses` and `/admin/chat` are all
translations onto the same use case.

**Every field here is either a handle or content, and the two are treated
differently.** The handles — who, which key, which capability, which model,
which request id — are the same values `UsageRecord` already carries, and are
safe in an ordinary log line. `messages`, `completion` and `reasoning` are not:
they are researchers' unpublished ideas typed into a box. Nothing in this
platform may put them anywhere but this table, which is why the entity carries
no `__str__` and why the repository never logs a row it failed to write.

**Nothing is truncated.** The audit log lost rows silently for months because a
value was wider than its column (PROGRESS.md 2026-08-02), and a transcript is
exactly the kind of value that is wide. The columns are unbounded text and the
bound on this table is time, applied by the retention sweep, which is a bound
that cannot be exceeded by one unusual request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.tenant import DEFAULT_TENANT_ID


@dataclass(frozen=True, slots=True)
class PromptLogSummary:
    """One transcript described without being disclosed.

    **The list and the transcript are two different reads, and that is the
    design rather than an optimisation.** A page of fifty entries carrying
    their full text would hand an operator fifty conversations to answer a
    question about one, load a few hundred megabytes to render a table, and
    make the audit record meaningless — "opened the logs page" is not the event
    worth recording. So the list returns this, which contains no message
    content at all, and reading an actual conversation is a second, deliberate
    request against a named id that writes an audit row.

    The sizes are here because they are what an operator picks a row by when
    the content is absent: an empty completion on a `stop` finish, or a prompt
    an order of magnitude larger than the rest, is visible from the table.
    """

    id: str
    at: datetime
    actor_id: str
    api_key_id: str | None
    capability: str
    model_alias: str
    request_id: str | None
    finish_reason: str | None
    completed: bool
    tool_calls: int
    message_chars: int
    completion_chars: int
    reasoning_chars: int
    truncated_fields: frozenset[str]
    tenant_id: str = DEFAULT_TENANT_ID


@dataclass(frozen=True, slots=True)
class PromptLogEntry:
    id: str
    at: datetime

    actor_id: str
    api_key_id: str | None
    """The `key_id` when the caller came through the gateway, None on the admin
    chat. Which of the two windows opened this record is recoverable from it:
    a row with a key was written because that key's window was open, a row
    without one because that person's was."""

    capability: str
    model_alias: str
    """Resolved, not requested. The caller names a capability and routing picks
    a model, so the alias is the only place a reader can learn which model
    produced the text below it — the request never said."""

    request_id: str | None
    """The `X-Request-Id` this conversation was served under, so a transcript
    joins to the log lines and the error the caller quoted. The reason the
    window is usually opened in the first place is a caller reporting a failure
    by its request id, and without this the transcript could not be found from
    it."""

    messages: str
    """The assembled prompt as JSON text: role, content, and any tool calls
    replayed into it.

    JSON rather than a rendered conversation because the ordering and the role
    boundaries are the part an operator is usually checking — "did the template
    actually get prepended", "did the passage arrive in a system message or a
    user one" — and a flattened rendering loses precisely that. Text rather
    than a JSON column because nothing queries inside it; it is read whole, by
    a person.
    """

    completion: str
    """What the model wrote, joined from the deltas that reached the client."""

    reasoning: str = ""
    """A thinking model's deliberation, kept apart from `completion` for the
    same reason `CompletionChunk` keeps it apart: it is not the answer, and
    concatenating them would misrepresent what the caller was sent. Empty when
    the model did not deliberate or the policy turned it off."""

    finish_reason: str | None = None
    completed: bool = True
    """False when the stream ended early — client disconnect, the token
    ceiling, the wall-clock deadline. A truncated transcript is worth keeping
    and worth labelling: "the model stopped here" and "the model was stopped
    here" are different findings, and the second is often the bug."""

    tool_calls: int = 0
    """How many tool calls the model emitted. A count rather than the calls
    themselves: the arguments are already in `completion`'s stream on the
    client side, and what an operator debugging an agent loop wants first is
    whether the model called anything at all — the failure this platform has
    actually seen is a model answering in prose where a call was expected
    (PROGRESS.md 2026-08-05)."""

    tenant_id: str = DEFAULT_TENANT_ID
    """Stamped by the scoped repository on write, read back through the same
    filter. A transcript is the most sensitive row in the schema, so it gets
    the boundary the audit log gets rather than a weaker one."""

    truncated_fields: frozenset[str] = field(default_factory=frozenset)
    """Which fields hit the per-row size guard, if any.

    Empty on every ordinary row. It exists so that the one bound this table
    does apply — a single request cannot write an unbounded amount — is
    *visible in the row it applied to* rather than inferred from a transcript
    that reads oddly at the end. Recording the fact beside the data is the
    lesson from the audit log's silent loss: a value that was cut says so.
    """
