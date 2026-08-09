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
