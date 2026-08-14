"""`/v1/responses`, tested against shapes a real client actually sent.

Every request body below is the one `codex-cli 0.147.0` put on the wire against
a local recorder on 2026-08-07, trimmed rather than invented. That matters more
here than usual: the endpoint exists because the runbook shipped a
configuration (`wire_api = "chat"`) that had been impossible for six months,
and the way that happened was writing to a specification instead of to a
client.
"""

from __future__ import annotations

import json

import pytest

from app.domain.entities.chat import CompletionChunk, MessageRole, ToolCall
from app.interfaces.http.responses_sse import _events
from app.interfaces.http.routers.responses import _collect, _to_domain, _tools
from app.interfaces.http.schemas.responses_schemas import ResponsesRequest

# --- request translation -----------------------------------------------------


def test_instructions_become_the_system_message() -> None:
    """`instructions` is a top-level string here, not a message.

    Reading it as anything else drops the entire system prompt — 20,751
    characters of it in the captured request — and the model answers with no
    idea what it is or what it may do.
    """
    request = ResponsesRequest(
        model="code",
        instructions="You are a coding agent running in the Codex CLI.",
        input=[
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}
        ],
    )

    messages = _to_domain(request)

    assert messages[0].role is MessageRole.SYSTEM
    assert messages[0].content == "You are a coding agent running in the Codex CLI."
    assert messages[1].role is MessageRole.USER


def test_the_developer_role_is_not_dropped() -> None:
    """Codex puts the sandbox and permission rules in a `developer` message.

    The domain has no such role. Mapping it to SYSTEM keeps the rules; dropping
    it would leave an agent believing it may write files it may not.
    """
    request = ResponsesRequest(
        model="code",
        input=[
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "sandbox_mode is read-only"}],
            }
        ],
    )

    messages = _to_domain(request)

    assert len(messages) == 1
    assert messages[0].role is MessageRole.SYSTEM
    assert "read-only" in messages[0].content


def test_a_replayed_tool_round_trip_survives_translation() -> None:
    """The shape of turn two, which is where an agent loop lives or dies.

    Codex replays its own `function_call` and the matching
    `function_call_output`, correlated by `call_id` — not by `id`, which is the
    item's own and differs. Losing the pairing leaves the model unable to tell
    which result belongs to which call.
    """
    request = ResponsesRequest(
        model="code",
        input=[
            {"type": "message", "role": "user", "content": "List the files here."},
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "exec_command",
                "arguments": '{"cmd":"ls"}',
            },
            {"type": "function_call_output", "id": "fco_1", "call_id": "call_1", "output": "a.txt"},
        ],
    )

    messages = _to_domain(request)

    assert [m.role for m in messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert messages[1].tool_calls[0].id == "call_1"
    assert messages[1].tool_calls[0].arguments == '{"cmd":"ls"}'
    assert messages[2].tool_call_id == "call_1"
    assert messages[2].content == "a.txt"


def test_reasoning_items_are_discarded_rather_than_replayed() -> None:
    """A model's deliberation never goes back into a prompt.

    The client sends these when `include: ["reasoning.encrypted_content"]` is
    set, which Codex does by default. Accepting the item and dropping it is the
    same rule `CompletionChunk.reasoning` states on the streaming side.
    """
    request = ResponsesRequest(
        model="code",
        input=[
            {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
            {"type": "message", "role": "user", "content": "hi"},
        ],
    )

    messages = _to_domain(request)

    assert len(messages) == 1
    assert messages[0].role is MessageRole.USER


def test_a_bare_string_input_is_accepted() -> None:
    """Legal in the API even though Codex always sends items."""
    assert _to_domain(ResponsesRequest(model="code", input="hello"))[0].content == "hello"


# --- tools -------------------------------------------------------------------


def test_a_namespace_is_flattened_not_dropped() -> None:
    """`multi_agent_v1` holds ordinary function tools the *client* executes.

    Treating the container as an unsupported capability would remove five
    working tools for no reason — the platform never runs any of them either
    way.
    """
    request = ResponsesRequest(
        model="code",
        input="hi",
        tools=[
            {"type": "function", "name": "exec_command", "parameters": {}},
            {
                "type": "namespace",
                "name": "multi_agent_v1",
                "tools": [
                    {"type": "function", "name": "spawn_agent", "parameters": {}},
                    {"type": "function", "name": "close_agent", "parameters": {}},
                ],
            },
        ],
    )

    tools, dropped = _tools(request)

    assert [t.name for t in tools] == ["exec_command", "spawn_agent", "close_agent"]
    assert dropped == []


def test_a_disabled_web_search_is_dropped_and_reported() -> None:
    """`external_web_access: false` is the client saying the tool is off.

    Dropping something already declared disabled is equivalent to honouring it,
    which is why the default Codex configuration works here. It is still named
    in the header, because a tool the model never saw should be findable by
    whoever wonders why it was not used.
    """
    request = ResponsesRequest(
        model="code",
        input="hi",
        tools=[{"type": "web_search", "external_web_access": False}],
    )

    tools, dropped = _tools(request)

    assert tools == []
    assert dropped == ["web_search"]


def test_an_unknown_tool_type_does_not_break_the_request() -> None:
    """A future client adding a tool type must not 422 every request.

    Dropped and named, like `web_search`. The alternative is that a Codex
    release nobody here has seen takes the whole integration down.
    """
    request = ResponsesRequest(
        model="code",
        input="hi",
        tools=[
            {"type": "function", "name": "exec_command", "parameters": {}},
            {"type": "computer_use_preview", "display_width": 1},
        ],
    )

    tools, dropped = _tools(request)

    assert [t.name for t in tools] == ["exec_command"]
    assert dropped == ["computer_use_preview"]


# --- tools declared inside `input` -------------------------------------------


def test_additional_tools_are_offered_to_the_model_not_dropped() -> None:
    """The item that 422'd every request from a post-capture client.

    A Codex newer than 0.147.0 puts `additional_tools` first in `input`, and it
    is a tool declaration rather than a turn — `role` scoping it, `tools`
    holding the same flat function objects the top-level field carries. The
    union had no tag for it, so pydantic refused the whole request before any
    of this ran.

    Accepting the item is only half of it. The tools inside are ones the client
    expects the model to be able to call, so they are offered; accepting the
    item and discarding its contents would have turned a loud 422 into an agent
    quietly missing tools it was told it had.
    """
    request = ResponsesRequest(
        model="code",
        input=[
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
            },
            {"type": "message", "role": "user", "content": "find it"},
        ],
        tools=[{"type": "function", "name": "exec_command", "parameters": {}}],
    )

    tools, dropped = _tools(request)
    messages = _to_domain(request)

    assert [t.name for t in tools] == ["exec_command", "lookup"]
    assert tools[1].parameters == {"type": "object", "properties": {}}
    assert dropped == []
    # It declares tools; it is not a turn, so it contributes no message.
    assert [m.role for m in messages] == [MessageRole.USER]


def test_a_tool_declared_in_both_places_is_offered_once() -> None:
    """Two entries under one name is a list no model can choose from."""
    request = ResponsesRequest(
        model="code",
        input=[
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [{"type": "function", "name": "exec_command", "description": "second"}],
            }
        ],
        tools=[{"type": "function", "name": "exec_command", "description": "first"}],
    )

    tools, _ = _tools(request)

    assert [t.name for t in tools] == ["exec_command"]
    # The documented field stays authoritative.
    assert tools[0].description == "first"


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


# --- what the fuse must not become -------------------------------------------


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


# --- the dropped headers ------------------------------------------------------


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


# --- streaming ---------------------------------------------------------------


async def _drain(chunks: list[CompletionChunk]) -> list[dict]:
    async def generation():  # type: ignore[no-untyped-def]
        for chunk in chunks:
            yield chunk

    events = []
    async for frame in _events(
        response_id="resp_test",
        created=0,
        model="code",
        generation=generation(),
        first=None,
    ):
        assert frame.startswith("event: "), "each frame carries an event line and a data line"
        events.append(json.loads(frame.split("data: ", 1)[1]))
    return events


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


async def test_a_tool_call_emits_the_four_events_the_client_needs() -> None:
    """The sequence a live client was observed to accept and act on.

    With these, `codex-cli 0.147.0` executed the call and came back with a
    `function_call_output`; the whole endpoint exists to reach that point.
    """
    events = await _drain(
        [
            CompletionChunk(
                delta="",
                finish_reason="tool_calls",
                tool_calls=(ToolCall(id="call_1", name="exec_command", arguments='{"cmd":"ls"}'),),
            )
        ]
    )

    types = [e["type"] for e in events]
    assert types == [
        "response.created",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    item = events[-1]["response"]["output"][0]
    assert item["type"] == "function_call"
    assert item["call_id"] == "call_1"
    assert item["arguments"] == '{"cmd":"ls"}'


async def test_there_is_no_done_sentinel() -> None:
    """Chat Completions ends with `data: [DONE]`; this protocol does not.

    Emitting it here would be a frame no client parses, and `sse.py` exists in
    part to keep that sentinel meaningful.
    """

    async def generation():  # type: ignore[no-untyped-def]
        yield CompletionChunk(delta="hi", token_count=1)

    frames = [
        f
        async for f in _events(
            response_id="r", created=0, model="code", generation=generation(), first=None
        )
    ]

    assert not any("[DONE]" in f for f in frames)
    assert json.loads(frames[-1].split("data: ", 1)[1])["type"] == "response.completed"


async def test_a_failure_ends_with_response_failed_not_completed() -> None:
    """The status line is gone once the first byte is out.

    `response.completed` after a failure would tell every client that treats
    the terminal event as success that a truncated answer was whole — the same
    lie `[DONE]` after an error frame would be on the other endpoint.
    """
    from app.domain.exceptions import NoAvailableModelError

    async def generation():  # type: ignore[no-untyped-def]
        yield CompletionChunk(delta="partial", token_count=1)
        raise NoAvailableModelError(detail="runtime died")

    events = []
    async for frame in _events(
        response_id="r", created=0, model="code", generation=generation(), first=None
    ):
        events.append(json.loads(frame.split("data: ", 1)[1]))

    assert events[-1]["type"] == "response.failed"
    assert events[-1]["response"]["error"]["code"] == "no_available_model"
    assert not any(e["type"] == "response.completed" for e in events)


async def test_a_truncated_answer_ends_with_response_incomplete() -> None:
    """The failure this endpoint shipped with, and the reason for `finish_reason`.

    A reply cut off at the context window is not a reply that finished, and
    until 2026-08-09 this module said it was: it ignored `finish_reason` and
    ended every stream that did not raise with `response.completed`. Codex
    rendered half a sentence as the final answer, with nothing anywhere saying
    otherwise. Real numbers behind it in the runbook, section 5.1.
    """
    events = await _drain(
        [
            CompletionChunk(delta="The first half of a sen", token_count=6),
            CompletionChunk(delta="", finish_reason="length", prompt_tokens=32231),
        ]
    )

    assert [e["type"] for e in events][-1] == "response.incomplete"
    assert not any(e["type"] == "response.completed" for e in events)

    final = events[-1]["response"]
    assert final["status"] == "incomplete"
    assert final["incomplete_details"] == {"reason": "max_output_tokens"}
    # The text that did arrive is still delivered. Truncated is not empty, and
    # a client that discarded it would lose output the caller was billed for.
    assert final["output"][0]["content"][0]["text"] == "The first half of a sen"
    assert final["output"][0]["status"] == "incomplete"


async def test_a_normal_answer_is_still_completed() -> None:
    """The other half of the branch, which is the one that must not regress.

    `"length"` is the only reason that means truncation; `"stop"` and
    `"tool_calls"` are ordinary ends, and reporting either as incomplete would
    tell an agent to continue a turn the model had finished.
    """
    for reason in ("stop", "tool_calls"):
        events = await _drain([CompletionChunk(delta="done", token_count=1, finish_reason=reason)])
        assert [e["type"] for e in events][-1] == "response.completed", reason
        assert events[-1]["response"]["status"] == "completed", reason
        assert "incomplete_details" not in events[-1]["response"], reason


async def test_the_non_streaming_body_reports_truncation_too() -> None:
    """`_collect` hardcoded `status="completed"`, which is the same defect.

    Codex always streams, so nothing caught it there — which is exactly why it
    is worth a test: the path with no client watching it is the one that stays
    wrong.
    """

    async def generation():  # type: ignore[no-untyped-def]
        yield CompletionChunk(delta="cut off here", token_count=3)
        yield CompletionChunk(delta="", finish_reason="length", prompt_tokens=32231)

    payload = await _collect("resp_x", 0, "code", generation())

    assert payload.status == "incomplete"
    assert payload.incomplete_details == {"reason": "max_output_tokens"}
    assert payload.output[0].status == "incomplete"  # type: ignore[union-attr]


@pytest.mark.parametrize("external", [True, False])
def test_web_search_is_refused_only_when_it_is_actually_wanted(external: bool) -> None:
    """The one capability here the platform genuinely cannot provide.

    Refusing the disabled form would refuse every default Codex request for a
    tool the client already turned off. Serving the enabled form would leave a
    model believing it can search the web while it silently never does, which
    is the failure `MLX_TOOL_CALLING_VERIFIED` exists to prevent.
    """
    from app.domain.exceptions import RuntimeCapabilityError
    from app.interfaces.http.routers.responses import _assert_no_server_side_tools

    request = ResponsesRequest(
        model="code",
        input="hi",
        tools=[{"type": "web_search", "external_web_access": external}],
    )

    if external:
        with pytest.raises(RuntimeCapabilityError):
            _assert_no_server_side_tools(request)
    else:
        _assert_no_server_side_tools(request)
