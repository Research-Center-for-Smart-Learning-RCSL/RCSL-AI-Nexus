"""Payload shapes a profile must be validated on before the guard trusts it.

`runtime_count_corpus.py` holds single user messages, which test the encoder.
The guard counts whole requests, so a profile is validated (#24 final spec
§6) on the shapes the gateway actually sends: tools, multi-turn tool loops,
thinking on and off, repeated content built to expose a segmentation deficit,
and sizes near the context boundary.

Each case is built from the gateway's own domain objects and encoded with the
same `message_payload`/`tool_payload` the Ollama adapter sends, so the runtime
and the counter see the same bytes. Counts are recorded by
`scripts/runtime-probes/record_validation_counts.py` into `RECORDED`, keyed by
weights digest; changing a case invalidates its counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.chat import Message, MessageRole, ToolCall, ToolDefinition

U, A, T, S = MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL, MessageRole.SYSTEM

TOOLS = (
    ToolDefinition(
        "read_file",
        "Read a file from the repository.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    ),
    ToolDefinition(
        "run_tests",
        "Run the unit tests matching a pattern.",
        {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
    ),
)

_CODE = (
    "def select(policy, models):\n"
    "    for c in sorted(policy.candidates, key=lambda c: -c.priority):\n"
    "        if (m := models.get(c.alias)) is not None:\n"
    "            return m\n"
    "    raise NoAvailableModelError(policy.capability)\n"
)


@dataclass(frozen=True)
class Case:
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...] = ()
    think: bool = False
    # Only for models whose context admits the case; near-boundary cases are
    # sized for one model and skipped on the rest.
    only: tuple[str, ...] = field(default=())


def _tool_loop(turns: int, result: str) -> tuple[Message, ...]:
    messages: list[Message] = [
        Message(S, "You are a code assistant."),
        Message(U, "Fix the routing bug."),
    ]
    for i in range(turns):
        call = ToolCall(f"call_{i}", "read_file", f'{{"path":"app/routing_{i}.py"}}')
        messages += [
            Message(A, "", tool_calls=(call,)),
            Message(T, result, tool_call_id=f"call_{i}", name="read_file"),
        ]
    messages.append(Message(U, "Now summarise what you found."))
    return tuple(messages)


CASES: dict[str, Case] = {
    "tools_plain": Case((Message(U, "Read the routing file."),), TOOLS),
    "system_multiturn": Case(
        (
            Message(S, "You are terse."),
            Message(U, "What is a capability?"),
            Message(A, "A named purpose a model serves."),
            Message(U, "And a routing policy?"),
        )
    ),
    "tool_loop_3": Case(_tool_loop(3, _CODE), TOOLS),
    "tool_loop_12": Case(_tool_loop(12, _CODE * 3), TOOLS),
    "think_on": Case((Message(U, "Why might a prefix cache miss?"),), think=True),
    "think_on_tools": Case(_tool_loop(2, _CODE), TOOLS, think=True),
    # Repetition is where a segmentation deficit compounds: Unigram may reach
    # pieces a merge tokenizer cannot, once per repeat (#25 review).
    "repeat_short_words": Case((Message(U, " a b" * 2000),)),
    "repeat_arrows": Case((Message(U, "x --> y <-- z => w ->> " * 600),)),
    "repeat_cjk_pairs": Case((Message(U, "的 是 在 了 " * 800),)),
    "repeat_indent_runs": Case((Message(U, ("\t  \t    x\n" * 1500)),)),
    # Near the boundary of the model each is sized for: within a few hundred
    # tokens of qwen2.5's 32768 with no output reserve, and at the gateway's
    # current per-model input limit (num_ctx // 2) for it.
    "near_boundary_qwen_32k": Case((Message(U, _CODE * 640),), only=("qwen2.5:7b",)),
    "near_boundary_qwen_16k": Case((Message(U, _CODE * 320),), only=("qwen2.5:7b",)),
}

# Recorded 2026-10-08 on the production host (Ollama 0.33.2).
RECORDED: dict[str, dict[str, object]] = {
    "2bada8a74506": {
        "counts": {
            "near_boundary_qwen_16k": 16029,
            "near_boundary_qwen_32k": 32029,
            "repeat_arrows": 5430,
            "repeat_cjk_pairs": 4030,
            "repeat_indent_runs": 6029,
            "repeat_short_words": 4029,
            "system_multiturn": 44,
            "tool_loop_12": 2486,
            "tool_loop_3": 465,
            "tools_plain": 190,
        },
        "manifest": "845dbda0ea48",
        "num_ctx": 32768,
        "ollama": "0.33.2",
        "ref": "qwen2.5:7b",
    },
    "a0feadb736f5": {
        "counts": {
            "repeat_arrows": 5413,
            "repeat_cjk_pairs": 3213,
            "repeat_indent_runs": 9008,
            "repeat_short_words": 4013,
            "system_multiturn": 49,
            "think_on": 23,
            "think_on_tools": 324,
            "tool_loop_12": 2800,
            "tool_loop_3": 422,
            "tools_plain": 112,
        },
        "manifest": "53dd8459790f",
        "num_ctx": 262144,
        "ollama": "0.33.2",
        "ref": "gemma4:31b-it-q8_0",
    },
}
