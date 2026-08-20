"""HTTP translation boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from app.domain.entities.chat import (
    Message,
    MessageRole,
    ToolCall,
)
from app.interfaces.http.schemas.responses_schemas import (
    InputAdditionalTools,
    InputFunctionCall,
    InputFunctionCallOutput,
    InputMessage,
    InputReasoning,
    InputTextPart,
    ResponsesRequest,
    UnknownInputItem,
)

DROPPED_TOOLS_HEADER = "X-Dropped-Tools"


DROPPED_INPUT_HEADER = "X-Dropped-Input-Items"


_UNSAFE_IN_HEADER = re.compile(r"[^A-Za-z0-9_.:-]")


_MAX_TOKEN_CHARS = 64


_MAX_HEADER_CHARS = 512


def _header_list(values: Sequence[str]) -> str:
    """Render client-supplied names into a value a header can actually carry.

    Both headers above name things the *client* typed: an unknown tool's `type`
    and an unknown item's `type` are arbitrary strings from the request body.
    Putting one straight into a header is how a request that this code was
    deliberately choosing to serve turns into a 500 instead — Starlette encodes
    header values as latin-1, so `{"type": "你好"}` raises `UnicodeEncodeError`
    on the response, after the work succeeded. A carriage return would be worse
    in kind if a downstream layer were ever the only thing rejecting it.

    So: a conservative charset, a bound per name, and a bound on the whole
    value, since the number of names is the client's choice too. A name that
    survives none of that is reported as `unprintable` rather than omitted — the
    point of the header is that the caller learns something was dropped, and
    that is still true when its name could not be repeated back.
    """
    tokens = [
        _UNSAFE_IN_HEADER.sub("", value)[:_MAX_TOKEN_CHARS] or "unprintable" for value in values
    ]
    rendered: list[str] = []
    length = 0
    for token in dict.fromkeys(tokens):
        if length + len(token) + 1 > _MAX_HEADER_CHARS:
            rendered.append("...")
            break
        rendered.append(token)
        length += len(token) + 1
    return ",".join(rendered)


def _text_of(content: str | list[InputTextPart]) -> str:
    """Parts joined without a separator, as `chat.py::_flatten` does.

    Inserting one would put characters into the prompt the caller did not send,
    and a client that splits a sentence across two parts would find a space in
    the middle of a word.
    """
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content)


def _output_text(output: str | list[InputTextPart] | dict[str, object]) -> str:
    """A tool result as the string a runtime takes.

    Codex sends a plain string, including for a tool that failed. The API also
    permits parts and an object; both are rendered rather than refused, because
    a caller whose tool returned structured data has not done anything wrong
    and the alternative is a 422 in the middle of an agent's loop.
    """
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "".join(part.text for part in output)
    return json.dumps(output, ensure_ascii=False)


def _to_domain(request: ResponsesRequest) -> list[Message]:
    """`instructions` plus `input`, in that order.

    `instructions` is a top-level string in this API and becomes the system
    message, which is the one message a model treats as authoritative. It is
    placed first and once; anything the caller also sent as a `system` or
    `developer` role stays where it was in `input`, because reordering a
    caller's conversation is not translation.
    """
    messages: list[Message] = []
    if request.instructions:
        messages.append(Message(role=MessageRole.SYSTEM, content=request.instructions))

    items = (
        [InputMessage(role="user", content=request.input)]
        if isinstance(request.input, str)
        else request.input
    )

    for item in items:
        if isinstance(item, InputMessage):
            # `developer` is this API's spelling of a system-authored
            # instruction and has no counterpart in the domain, which models
            # the three roles a runtime accepts. Mapped to SYSTEM rather than
            # dropped: it carries the sandbox and permission rules an agent
            # depends on.
            role = MessageRole.SYSTEM if item.role == "developer" else MessageRole(item.role)
            messages.append(Message(role=role, content=_text_of(item.content)))
        elif isinstance(item, InputFunctionCall):
            # The model's own previous call, replayed. It belongs on an
            # assistant message with no content, which is the shape both
            # runtimes take history in.
            messages.append(
                Message(
                    role=MessageRole.ASSISTANT,
                    content="",
                    tool_calls=(
                        ToolCall(id=item.call_id, name=item.name, arguments=item.arguments),
                    ),
                )
            )
        elif isinstance(item, InputFunctionCallOutput):
            messages.append(
                Message(
                    role=MessageRole.TOOL,
                    content=_output_text(item.output),
                    tool_call_id=item.call_id,
                )
            )
        elif isinstance(item, InputReasoning):
            # Discarded. A model's deliberation is never replayed into a
            # prompt; see `CompletionChunk.reasoning`.
            continue
        elif isinstance(item, InputAdditionalTools):
            # Not conversation at all: it declares tools, which `_tools`
            # collects from here. Nothing in it is a turn, so nothing in it
            # belongs in the message list.
            continue
        elif isinstance(item, UnknownInputItem):
            # An item type newer than this gateway. Dropped so that the rest of
            # the conversation still reaches the model, and named in
            # `DROPPED_INPUT_HEADER` so the loss is not silent.
            continue

    return messages


def _dropped_input_items(request: ResponsesRequest) -> list[str]:
    """The unrecognised item types, each named once.

    Deduplicated because a long conversation replays its history every turn: an
    unknown type appearing forty times would put forty copies into a header,
    and the one thing a header must not do is grow with the transcript.
    """
    if not isinstance(request.input, list):
        return []
    return list(
        dict.fromkeys(item.type for item in request.input if isinstance(item, UnknownInputItem))
    )
