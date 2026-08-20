from __future__ import annotations

import pytest

from app.domain.entities.chat import CompletionChunk, MessageRole
from app.interfaces.http.routers.responses import _to_domain, _tools
from app.interfaces.http.schemas.responses_schemas import ResponsesRequest
from tests.unit.responses_api_fixtures import (
    _drain,
)

pytest_plugins = ("tests.unit.responses_api_fixtures",)


def test_web_search_inside_additional_tools_is_still_refused() -> None:
    """The guardrail reads both declaration sites or it reads neither.

    A capability check that only looks at `tools` is one an unchanged client
    walks straight past by declaring the same tool one field over.
    """
    from app.domain.exceptions import RuntimeCapabilityError
    from app.interfaces.http.routers.responses import _assert_no_server_side_tools

    request = ResponsesRequest(
        model="code",
        input=[
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [{"type": "web_search", "external_web_access": True}],
            }
        ],
    )

    with pytest.raises(RuntimeCapabilityError):
        _assert_no_server_side_tools(request)


def test_an_unknown_input_item_costs_the_item_not_the_request() -> None:
    """`tools` has had this fuse since 2026-08-05; `input` had none.

    `ResponseItem` in `codex-rs/protocol` carries a dozen variants no capture
    here has exercised. Any one of them arriving must cost the caller that
    item, not every request they make.
    """
    from app.interfaces.http.routers.responses import _dropped_input_items

    request = ResponsesRequest(
        model="code",
        input=[
            {"type": "local_shell_call", "id": "lsc_1", "action": {"command": ["ls"]}},
            {"type": "message", "role": "user", "content": "hi"},
            {"type": "local_shell_call", "id": "lsc_2", "action": {"command": ["pwd"]}},
        ],
    )

    messages = _to_domain(request)

    assert [m.role for m in messages] == [MessageRole.USER]
    # Named once, however often history replays it: a header must not grow with
    # the transcript.
    assert _dropped_input_items(request) == ["local_shell_call"]


def test_a_malformed_known_item_is_still_refused() -> None:
    """The fuse must not become a place for broken requests to hide.

    A `function_call` without its `call_id` is malformed, not unrecognised. An
    ordered union would have matched it as an unknown item and dropped it
    silently; the callable discriminator sends it to the model that names the
    missing field.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="call_id"):
        ResponsesRequest(
            model="code",
            input=[{"type": "function_call", "name": "exec_command", "arguments": "{}"}],
        )


@pytest.mark.parametrize("tag", [{"a": 1}, ["x"], 3, None])
def test_a_non_string_type_is_refused_rather_than_crashing(tag: object) -> None:
    """The fuse must not hand the server a worse failure than the one it fixed.

    The tag is looked up in a set, and `{"a": 1} in frozenset(...)` raises
    `TypeError: unhashable type` — not a `ValidationError`, so it escapes the
    handler that turns bad bodies into 422s and becomes a 500. A malformed
    request taking that path is the opposite of what accepting unknown items is
    for.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResponsesRequest(model="code", input=[{"type": tag}])


def test_additional_tools_without_a_role_still_works() -> None:
    """`role` is required upstream, unused here, and therefore optional here.

    Demanding a field nothing reads would let a client build that renamed it
    take every request down again, which is the outage this item type was added
    to end.
    """
    request = ResponsesRequest(
        model="code",
        input=[
            {
                "type": "additional_tools",
                "tools": [{"type": "function", "name": "lookup"}],
            }
        ],
    )

    tools, _ = _tools(request)

    assert [t.name for t in tools] == ["lookup"]


def test_a_duplicate_tool_name_is_reported_not_only_suppressed() -> None:
    """Same name does not mean same tool.

    A client's own `send_input` beside `multi_agent_v1.send_input` leaves the
    model holding the first one's schema for the second one's job. Suppressing
    the second is right; suppressing it silently is the narrowing the header
    exists to surface.
    """
    request = ResponsesRequest(
        model="code",
        input="hi",
        tools=[
            {"type": "function", "name": "send_input", "parameters": {"type": "object"}},
            {
                "type": "namespace",
                "name": "multi_agent_v1",
                "tools": [{"type": "function", "name": "send_input", "parameters": {}}],
            },
        ],
    )

    tools, dropped = _tools(request)

    assert [t.name for t in tools] == ["send_input"]
    assert dropped == ["duplicate:send_input"]


def test_an_input_of_only_unknown_items_is_refused() -> None:
    """`chat_schemas` says this with `min_length=1`; here it cannot.

    Items are accepted and dropped by design, so an `input` that was not empty
    on the wire can be empty by the time it reaches a runtime. Forwarding a
    prompt with no turns bills the caller for an answer to nothing.
    """
    from fastapi.exceptions import RequestValidationError

    from app.interfaces.http.routers.responses import _assert_something_to_send

    request = ResponsesRequest(
        model="code",
        input=[{"type": "compaction", "id": "c_1"}, {"type": "reasoning", "id": "r_1"}],
    )

    with pytest.raises(RequestValidationError):
        _assert_something_to_send(_to_domain(request))


def test_a_dropped_name_cannot_break_the_response() -> None:
    """The names in these headers are strings the *client* chose.

    Starlette encodes header values as latin-1, so a tool or item type holding
    non-latin-1 characters raised `UnicodeEncodeError` on a response the code
    had deliberately decided to serve — turning a dropped item into a 500.
    """
    from starlette.responses import Response as StarletteResponse

    from app.interfaces.http.routers.responses import DROPPED_INPUT_HEADER, _header_list

    rendered = _header_list(["你好", "local_shell_call", "with\r\ninjection"])

    assert rendered == "unprintable,local_shell_call,withinjection"
    # The property that matters is not the exact string: it is that the header
    # can actually be sent.
    StarletteResponse(status_code=200, headers={DROPPED_INPUT_HEADER: rendered})


def test_the_header_does_not_grow_without_bound() -> None:
    """The number of names is the client's choice too."""
    from app.interfaces.http.routers.responses import _header_list

    rendered = _header_list([f"item_type_number_{n}" for n in range(200)])

    assert len(rendered) <= 512 + len("...")
    assert rendered.endswith("...")


async def test_a_text_answer_opens_and_closes_one_item() -> None:
    events = await _drain(
        [
            CompletionChunk(delta="Hello", token_count=1),
            CompletionChunk(delta=" world", token_count=1),
            CompletionChunk(delta="", finish_reason="stop", prompt_tokens=7),
        ]
    )

    types = [e["type"] for e in events]
    assert types == [
        "response.created",
        "response.output_item.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.output_item.done",
        "response.completed",
    ]
    final = events[-1]["response"]
    assert final["output"][0]["content"][0]["text"] == "Hello world"
    assert final["usage"] == {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9}
