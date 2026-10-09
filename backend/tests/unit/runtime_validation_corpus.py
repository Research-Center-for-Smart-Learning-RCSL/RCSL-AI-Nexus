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
from typing import Any

from app.adapters.runtime.ollama_adapter.encoding import message_payload, tool_payload
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
    # The gateway's own flag. The adapter sends `think: false` when it is off
    # and *omits* the field when it is on (`generation.py:83`), so that is what
    # `wire_payload` sends. `explicit_think` is a separate runtime experiment,
    # `think: true` on the wire, which the gateway never sends.
    thinking: bool = False
    explicit_think: bool = False
    # Only for models whose context admits the case; near-boundary cases are
    # sized for one model and skipped on the rest.
    only: tuple[str, ...] = field(default=())


def wire_payload(ref: str, case: Case, num_ctx: int) -> dict[str, Any]:
    """The `/api/chat` body the Ollama adapter would send for this case."""
    body: dict[str, Any] = {
        "model": ref,
        "messages": [message_payload(m) for m in case.messages],
        "stream": False,
        "keep_alive": -1,
        "options": {"num_ctx": num_ctx, "num_predict": 1},
    }
    if case.tools:
        body["tools"] = tool_payload(case.tools)
    if case.explicit_think:
        body["think"] = True
    elif not case.thinking:
        body["think"] = False
    return body


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
    # Rounds varied with identical content per round, then content varied at a
    # fixed round count, so renderer overhead per round and content
    # segmentation can be told apart (review on #24).
    "tool_loop_3": Case(_tool_loop(3, _CODE), TOOLS),
    "tool_loop_12": Case(_tool_loop(12, _CODE), TOOLS),
    "tool_loop_50": Case(_tool_loop(50, _CODE), TOOLS),
    "tool_loop_100": Case(_tool_loop(100, _CODE), TOOLS),
    "tool_loop_12_result_x3": Case(_tool_loop(12, _CODE * 3), TOOLS),
    "tool_loop_12_result_x9": Case(_tool_loop(12, _CODE * 9), TOOLS),
    "thinking_gateway": Case((Message(U, "Why might a prefix cache miss?"),), thinking=True),
    "thinking_gateway_tools": Case(_tool_loop(2, _CODE), TOOLS, thinking=True),
    "think_true_on_wire": Case(
        (Message(U, "Why might a prefix cache miss?"),), explicit_think=True
    ),
    # Repetition is where a segmentation deficit would compound: Unigram could
    # reach pieces a merge tokenizer cannot, once per repeat (#25 review). The
    # counter now merges as the runtime does (C6b); the cases stay as a check.
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

# Recorded 2026-10-08 on the production host (Ollama 0.33.2). Every count was
# requested with `truncate: false`, which the runtime refuses rather than
# shortening, so each is a count of the whole payload.
RECORDED: dict[str, dict[str, object]] = {
    "2bada8a74506": {
        "cases": {
            "near_boundary_qwen_16k": {
                "completeness": "truncate:false accepted",
                "count": 16029,
                "payload_sha256": "b3e8443b9d171694",
                "think_on_wire": False,
            },
            "near_boundary_qwen_32k": {
                "completeness": "truncate:false accepted",
                "count": 32029,
                "payload_sha256": "afa2b32d351413fd",
                "think_on_wire": False,
            },
            "repeat_arrows": {
                "completeness": "truncate:false accepted",
                "count": 5430,
                "payload_sha256": "2c9d611c91e5160e",
                "think_on_wire": False,
            },
            "repeat_cjk_pairs": {
                "completeness": "truncate:false accepted",
                "count": 4030,
                "payload_sha256": "3eed8da879e83097",
                "think_on_wire": False,
            },
            "repeat_indent_runs": {
                "completeness": "truncate:false accepted",
                "count": 6029,
                "payload_sha256": "e5232f51fa47577e",
                "think_on_wire": False,
            },
            "repeat_short_words": {
                "completeness": "truncate:false accepted",
                "count": 4029,
                "payload_sha256": "b843c4760d08bb7e",
                "think_on_wire": False,
            },
            "system_multiturn": {
                "completeness": "truncate:false accepted",
                "count": 44,
                "payload_sha256": "0563955bf4513e1e",
                "think_on_wire": False,
            },
            "thinking_gateway": {
                "completeness": "truncate:false accepted",
                "count": 36,
                "payload_sha256": "7ea35f5b4ccb2080",
                "think_on_wire": "omitted",
            },
            "thinking_gateway_tools": {
                "completeness": "truncate:false accepted",
                "count": 374,
                "payload_sha256": "ef29099309783b20",
                "think_on_wire": "omitted",
            },
            "tool_loop_100": {
                "completeness": "truncate:false accepted",
                "count": 9382,
                "payload_sha256": "8442b3b1ed2cf49b",
                "think_on_wire": False,
            },
            "tool_loop_12": {
                "completeness": "truncate:false accepted",
                "count": 1286,
                "payload_sha256": "1fdaf3244542ab2d",
                "think_on_wire": False,
            },
            "tool_loop_12_result_x3": {
                "completeness": "truncate:false accepted",
                "count": 2486,
                "payload_sha256": "1ab1d3f641f77c5c",
                "think_on_wire": False,
            },
            "tool_loop_12_result_x9": {
                "completeness": "truncate:false accepted",
                "count": 6086,
                "payload_sha256": "2880f0cf54359918",
                "think_on_wire": False,
            },
            "tool_loop_3": {
                "completeness": "truncate:false accepted",
                "count": 465,
                "payload_sha256": "1a3a66e6545557a0",
                "think_on_wire": False,
            },
            "tool_loop_50": {
                "completeness": "truncate:false accepted",
                "count": 4782,
                "payload_sha256": "3dc57b2131bdda09",
                "think_on_wire": False,
            },
            "tools_plain": {
                "completeness": "truncate:false accepted",
                "count": 190,
                "payload_sha256": "49af1dc238326d3c",
                "think_on_wire": False,
            },
        },
        "manifest": "845dbda0ea48",
        "num_ctx": 32768,
        "ollama": "0.33.2",
        "ref": "qwen2.5:7b",
    },
    "a0feadb736f5": {
        "cases": {
            "repeat_arrows": {
                "completeness": "truncate:false accepted",
                "count": 5413,
                "payload_sha256": "d43c5068e17d7a88",
                "think_on_wire": False,
            },
            "repeat_cjk_pairs": {
                "completeness": "truncate:false accepted",
                "count": 3213,
                "payload_sha256": "0e3218ed9af9cd1d",
                "think_on_wire": False,
            },
            "repeat_indent_runs": {
                "completeness": "truncate:false accepted",
                "count": 9008,
                "payload_sha256": "34428b47876f786b",
                "think_on_wire": False,
            },
            "repeat_short_words": {
                "completeness": "truncate:false accepted",
                "count": 4013,
                "payload_sha256": "2cf783dac22a6bef",
                "think_on_wire": False,
            },
            "system_multiturn": {
                "completeness": "truncate:false accepted",
                "count": 49,
                "payload_sha256": "a6dd2fc4d39e3378",
                "think_on_wire": False,
            },
            "think_true_on_wire": {
                "completeness": "truncate:false accepted",
                "count": 23,
                "payload_sha256": "2bfe8b18e00ba983",
                "think_on_wire": True,
            },
            "thinking_gateway": {
                "completeness": "truncate:false accepted",
                "count": 23,
                "payload_sha256": "821820f57de5cf78",
                "think_on_wire": "omitted",
            },
            "thinking_gateway_tools": {
                "completeness": "truncate:false accepted",
                "count": 324,
                "payload_sha256": "5637e71f99ad9201",
                "think_on_wire": "omitted",
            },
            "tool_loop_100": {
                "completeness": "truncate:false accepted",
                "count": 9824,
                "payload_sha256": "09f942f71e488e8d",
                "think_on_wire": False,
            },
            "tool_loop_12": {
                "completeness": "truncate:false accepted",
                "count": 1288,
                "payload_sha256": "f90e13f9f092ee9d",
                "think_on_wire": False,
            },
            "tool_loop_12_result_x3": {
                "completeness": "truncate:false accepted",
                "count": 2800,
                "payload_sha256": "28fe8b42dbf51009",
                "think_on_wire": False,
            },
            "tool_loop_12_result_x9": {
                "completeness": "truncate:false accepted",
                "count": 7336,
                "payload_sha256": "289fb20073af3a25",
                "think_on_wire": False,
            },
            "tool_loop_3": {
                "completeness": "truncate:false accepted",
                "count": 422,
                "payload_sha256": "d86896de95127d2f",
                "think_on_wire": False,
            },
            "tool_loop_50": {
                "completeness": "truncate:false accepted",
                "count": 4974,
                "payload_sha256": "dbb69b7d5633b990",
                "think_on_wire": False,
            },
            "tools_plain": {
                "completeness": "truncate:false accepted",
                "count": 112,
                "payload_sha256": "0801622b646ceb6b",
                "think_on_wire": False,
            },
        },
        "manifest": "53dd8459790f",
        "num_ctx": 262144,
        "ollama": "0.33.2",
        "ref": "gemma4:31b-it-q8_0",
    },
}
