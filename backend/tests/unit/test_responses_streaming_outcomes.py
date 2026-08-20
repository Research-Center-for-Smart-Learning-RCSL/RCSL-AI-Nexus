from __future__ import annotations

import json

import pytest

from app.domain.entities.chat import CompletionChunk, ToolCall
from app.interfaces.http.responses_sse import _events
from app.interfaces.http.routers.responses import _collect
from app.interfaces.http.schemas.responses_schemas import ResponsesRequest
from tests.unit.responses_api_fixtures import (
    _drain,
)

pytest_plugins = ("tests.unit.responses_api_fixtures",)


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
