from __future__ import annotations

from app.domain.entities.chat import MessageRole
from app.interfaces.http.routers.responses import _to_domain, _tools
from app.interfaces.http.schemas.responses_schemas import ResponsesRequest

pytest_plugins = ("tests.unit.responses_api_fixtures",)


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
