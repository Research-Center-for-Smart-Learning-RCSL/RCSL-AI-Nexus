"""What every runtime adapter has to decide about tool calling.

Two questions come up identically in each adapter and are answered here so the
answers cannot drift apart: whether the tools are sent at all, and what to do
with a `tool_choice` no runtime here can enforce.
"""

from __future__ import annotations

from app.domain.entities.chat import ToolChoice, ToolChoiceMode
from app.domain.exceptions import RuntimeCapabilityError


def should_send_tools(tool_choice: ToolChoice | None, runtime: str) -> bool:
    """Whether to put the tools on the wire, refusing what cannot be honoured.

    NONE is exact everywhere and needs nothing from the runtime: withholding the
    tools is precisely "do not call one". AUTO is the default and the only mode
    an agent client normally sends.

    REQUIRED and FUNCTION are refused rather than downgraded. Both ask the
    runtime to constrain decoding so that a call is certain, which neither
    runtime here exposes a way to demand; a caller quietly given AUTO instead
    receives prose where their parser expects a call, and finds out somewhere
    far from the request that caused it. This is the same judgement the MLX
    adapter makes on `embed` and `unload` — refusing beats answering plausibly
    and wrongly.
    """
    if tool_choice is None or tool_choice.mode is ToolChoiceMode.AUTO:
        return True
    if tool_choice.mode is ToolChoiceMode.NONE:
        return False
    raise RuntimeCapabilityError(
        detail=f"{runtime} cannot constrain tool choice; "
        f"tool_choice={tool_choice.mode.value!r} is not supported, use 'auto' or 'none'"
    )
