"""HTTP tools boundary."""

from __future__ import annotations

from fastapi.exceptions import RequestValidationError

from app.domain.entities.chat import (
    Message,
    SamplingOptions,
    ToolChoice,
    ToolChoiceMode,
    ToolDefinition,
)
from app.domain.exceptions import RuntimeCapabilityError
from app.interfaces.http.schemas.responses_schemas import (
    FunctionTool,
    InputAdditionalTools,
    NamespaceTool,
    ResponsesRequest,
    ToolChoiceFunction,
    ToolItem,
    WebSearchTool,
)


def _declared_tools(request: ResponsesRequest) -> list[ToolItem]:
    """Every tool the client declared, from both places it can declare one.

    `tools` is the documented field and an `additional_tools` item inside
    `input` is the second; a client that uses the latter puts ordinary function
    tools there and expects the model to be able to call them. Both are read
    through this one function so that the guardrail below and the translation
    above can never disagree about what was actually offered.
    """
    declared = list(request.tools)
    if isinstance(request.input, list):
        for item in request.input:
            if isinstance(item, InputAdditionalTools):
                declared.extend(item.tools)
    return declared


def _tools(request: ResponsesRequest) -> tuple[list[ToolDefinition], list[str]]:
    """Flatten what the platform can serve, and name what it dropped.

    Reads from `_declared_tools`, so a tool declared in an `additional_tools`
    input item is offered exactly like one declared in `tools`.

    A `namespace` is a container of ordinary function tools — Codex sends
    `multi_agent_v1` holding five, every one executed by the *client* — so
    flattening it costs nothing and offering it costs nothing either. Dropping
    it would have removed a working capability for no reason.

    `web_search` is the one thing here the platform genuinely cannot do: it is
    server-side, and performing it would mean the gateway making outbound web
    requests, against the data plane's segmentation (security.md §6) and its
    SSRF stance (§7.2). Refused only when the client actually wants it; see
    `_assert_no_server_side_tools`.
    """
    definitions: list[ToolDefinition] = []
    dropped: list[str] = []
    seen: set[str] = set()

    def add(tool: FunctionTool) -> None:
        # A client declaring the same tool in `tools` and again in an
        # `additional_tools` item is not an error, but handing a runtime two
        # entries under one name is a list no model can choose from. The first
        # declaration wins, which keeps the documented field authoritative.
        #
        # Reported rather than merely suppressed, because the benign reading is
        # not the only one: two tools can share a name without being the same
        # tool — a client's own `send_input` beside `multi_agent_v1.send_input`
        # — and then the model is offered the first one's schema for the second
        # one's job. That is a narrowing, and an unreported narrowing is the
        # thing this header exists to prevent.
        if tool.name in seen:
            dropped.append(f"duplicate:{tool.name}")
            return
        seen.add(tool.name)
        definitions.append(
            ToolDefinition(
                name=tool.name,
                # `description` is not optional in the domain; a tool without one
                # is offered with an empty string rather than refused.
                description=tool.description or "",
                parameters=tool.parameters,
            )
        )

    for tool in _declared_tools(request):
        if isinstance(tool, FunctionTool):
            add(tool)
        elif isinstance(tool, NamespaceTool):
            for nested in tool.tools:
                add(nested)
        elif isinstance(tool, WebSearchTool):
            dropped.append("web_search")
        else:
            dropped.append(getattr(tool, "type", "unknown"))

    return definitions, dropped


def _assert_something_to_send(messages: list[Message]) -> None:
    """Refuse a request that translated to no conversation at all.

    `chat_schemas.py` states this as `min_length=1` on `messages`, which the
    schema can enforce because nothing there disappears between parsing and
    sending. Here it can't: `reasoning` and unrecognised items are accepted and
    dropped by design, so an `input` that was not empty on the wire can be empty
    by the time it reaches a runtime.

    Before this, such a request was forwarded as a prompt with no turns and the
    caller got whatever the runtime made of that — a paid-for answer to nothing,
    or an adapter error attributed to the platform. A 422 in the same shape the
    other endpoint gives is both truthful and the one the caller can act on.
    """
    if messages:
        return
    raise RequestValidationError(
        [
            {
                "type": "too_short",
                "loc": ("body", "input"),
                "msg": "no message survived translation; every item was of a type this "
                "gateway does not send",
            }
        ]
    )


def _assert_no_server_side_tools(request: ResponsesRequest) -> None:
    """Refuse a web search that was actually asked for.

    `external_web_access: false` is the client saying the tool is off, and
    dropping something already declared disabled is equivalent to honouring it
    — which is why the default Codex configuration works here. `true` is a
    request for a capability this deployment does not have, and serving it
    silently would leave a model believing it can search while it never does.
    That is the failure `MLX_TOOL_CALLING_VERIFIED` exists to prevent, and the
    reason to fail at the moment the switch is turned on rather than three
    hours into a task.
    """
    for tool in _declared_tools(request):
        if isinstance(tool, WebSearchTool) and tool.external_web_access:
            raise RuntimeCapabilityError(
                detail="web_search with external_web_access is not served by this deployment"
            )


def _tool_choice(request: ResponsesRequest) -> ToolChoice | None:
    if request.tool_choice is None:
        return None
    if isinstance(request.tool_choice, ToolChoiceFunction):
        return ToolChoice(mode=ToolChoiceMode.FUNCTION, function_name=request.tool_choice.name)
    return ToolChoice(mode=ToolChoiceMode(request.tool_choice))


def _sampling(request: ResponsesRequest) -> SamplingOptions | None:
    options = SamplingOptions(temperature=request.temperature, top_p=request.top_p)
    return None if options.is_empty() else options
