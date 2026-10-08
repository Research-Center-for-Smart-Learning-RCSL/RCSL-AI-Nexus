# ruff: noqa: E501 - recorded runtime output, kept byte for byte
"""Prompts rendered by the runtime itself, the bytes the gemma4 port must equal.

Recorded 2026-10-08 from Ollama 0.33.2 on the production host, `gemma4:31b-it-q8_0`,
with `_debug_render_only: true` and `truncate: false`, from the payloads below.
`render_diff.py` re-checks the port against a live runtime; this pins it in CI.
Re-record (`scripts/runtime-probes/render_diff.py`) rather than edit by hand.
"""

from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "function": {
            "description": "Search the index.",
            "name": "search",
            "parameters": {
                "properties": {
                    "filters": {
                        "description": "Nested",
                        "properties": {
                            "lang": {"type": "string"},
                            "since": {"nullable": True, "type": "string"},
                        },
                        "required": ["lang"],
                        "type": "object",
                    },
                    "flag": {"type": "boolean"},
                    "limit": {"type": "integer"},
                    "loose": {"type": "object"},
                    "maybe": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    "mode": {"enum": ["fast", "exact", 3], "type": "string"},
                    "query": {"description": "What to find", "type": "string"},
                    "rows": {
                        "items": {
                            "properties": {
                                "id": {"type": "integer"},
                                "label": {"description": "x", "type": "string"},
                            },
                            "required": ["id"],
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "score": {"description": "Threshold", "type": ["number", "null"]},
                    "tags": {"items": {"enum": ["a", "b"], "type": "string"}, "type": "array"},
                },
                "required": ["query", "filters"],
                "type": "object",
            },
        },
        "type": "function",
    },
    {
        "function": {
            "description": "",
            "name": "noop",
            "parameters": {"properties": {}, "type": "object"},
        },
        "type": "function",
    },
]

CASES: dict[str, list[dict[str, Any]]] = {
    "call_then_content": [
        {"content": "q", "role": "user"},
        {
            "content": "Let me look.",
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": {
                            "big": 1e21,
                            "filters": {"lang": "zh", "z": [1, "two", {"k": False}]},
                            "flag": True,
                            "limit": 3,
                            "none": None,
                            "query": "x y",
                            "score": 0.25,
                            "small": 1.5e-07,
                            "tags": [],
                        },
                        "name": "search",
                    },
                    "id": "c1",
                }
            ],
        },
        {"content": "res", "role": "tool", "tool_call_id": "c1"},
        {"content": "Done.", "role": "assistant"},
        {"content": "thanks", "role": "user"},
    ],
    "call_without_response": [
        {"content": "q", "role": "user"},
        {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": {
                            "big": 1e21,
                            "filters": {"lang": "zh", "z": [1, "two", {"k": False}]},
                            "flag": True,
                            "limit": 3,
                            "none": None,
                            "query": "x y",
                            "score": 0.25,
                            "small": 1.5e-07,
                            "tags": [],
                        },
                        "name": "search",
                    },
                    "id": "c1",
                }
            ],
        },
    ],
    "consecutive_assistant": [
        {"content": "q", "role": "user"},
        {"content": "part one", "role": "assistant"},
        {"content": "part two", "role": "assistant"},
        {"content": "ok", "role": "user"},
    ],
    "developer_role": [
        {"content": "dev rules", "role": "developer"},
        {"content": "q", "role": "user"},
    ],
    "empty_user": [{"content": "", "role": "user"}],
    "ends_with_tool": [
        {"content": "q", "role": "user"},
        {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": {
                            "big": 1e21,
                            "filters": {"lang": "zh", "z": [1, "two", {"k": False}]},
                            "flag": True,
                            "limit": 3,
                            "none": None,
                            "query": "x y",
                            "score": 0.25,
                            "small": 1.5e-07,
                            "tags": [],
                        },
                        "name": "search",
                    },
                    "id": "c1",
                }
            ],
        },
        {"content": "last", "role": "tool", "tool_call_id": "c1"},
    ],
    "schema_and_args": [
        {"content": "  sys with spaces \n", "role": "system"},
        {"content": "  hi  ", "role": "user"},
        {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": {
                            "big": 1e21,
                            "filters": {"lang": "zh", "z": [1, "two", {"k": False}]},
                            "flag": True,
                            "limit": 3,
                            "none": None,
                            "query": "x y",
                            "score": 0.25,
                            "small": 1.5e-07,
                            "tags": [],
                        },
                        "name": "search",
                    },
                    "id": "c1",
                },
                {"function": {"arguments": {}, "name": "noop"}, "id": "c2"},
            ],
        },
        {"content": 'r1 "quoted"', "role": "tool", "tool_call_id": "c1", "tool_name": "search"},
        {"content": " r2 ", "role": "tool", "tool_call_id": "c2"},
        {"content": "next", "role": "user"},
    ],
    "thought_in_content": [
        {"content": "q", "role": "user"},
        {"content": "<|channel>hidden<channel|>  visible  ", "role": "assistant"},
        {"content": "again", "role": "user"},
    ],
    "tool_resp_no_id": [
        {"content": "q", "role": "user"},
        {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": {
                            "big": 1e21,
                            "filters": {"lang": "zh", "z": [1, "two", {"k": False}]},
                            "flag": True,
                            "limit": 3,
                            "none": None,
                            "query": "x y",
                            "score": 0.25,
                            "small": 1.5e-07,
                            "tags": [],
                        },
                        "name": "search",
                    },
                    "id": "c1",
                }
            ],
        },
        {"content": "only name", "role": "tool", "tool_name": "search"},
    ],
    "tool_resp_unknown": [
        {"content": "q", "role": "user"},
        {
            "content": "",
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "arguments": {
                            "big": 1e21,
                            "filters": {"lang": "zh", "z": [1, "two", {"k": False}]},
                            "flag": True,
                            "limit": 3,
                            "none": None,
                            "query": "x y",
                            "score": 0.25,
                            "small": 1.5e-07,
                            "tags": [],
                        },
                        "name": "search",
                    },
                    "id": "c1",
                }
            ],
        },
        {"content": "anon", "role": "tool"},
    ],
    "unit_sep_whitespace": [{"content": "\x1ckeep\x1f  ", "role": "user"}],
}

RENDERED: dict[str, str] = {
    "call_then_content/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:search{value:<|"|>res<|"|>}<tool_response|>Let '
    "me look.Done.<turn|>\n"
    "<|turn>user\n"
    "thanks<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "call_then_content/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:search{value:<|"|>res<|"|>}<tool_response|>Let '
    "me look.Done.<turn|>\n"
    "<|turn>user\n"
    "thanks<turn|>\n"
    "<|turn>model\n",
    "call_without_response/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>',
    "call_without_response/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>',
    "consecutive_assistant/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    "part onepart two<turn|>\n"
    "<|turn>user\n"
    "ok<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "consecutive_assistant/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    "part onepart two<turn|>\n"
    "<|turn>user\n"
    "ok<turn|>\n"
    "<|turn>model\n",
    "developer_role/think=False": "<bos><|turn>system\n"
    'dev rules<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "developer_role/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    'dev rules<|tool>declaration:search{description:<|"|>Search '
    "the "
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n",
    "empty_user/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "empty_user/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "<turn|>\n"
    "<|turn>model\n",
    "ends_with_tool/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:search{value:<|"|>last<|"|>}<tool_response|>',
    "ends_with_tool/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:search{value:<|"|>last<|"|>}<tool_response|><|channel>thought\n',
    "schema_and_args/think=False": "<bos><|turn>system\n"
    "sys with "
    'spaces<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "hi<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_call>call:noop{}<tool_call|><|tool_response>response:search{value:<|"|>r1 '
    '"quoted"<|"|>}<tool_response|><|tool_response>response:noop{value:<|"|> '
    'r2 <|"|>}<tool_response|><turn|>\n'
    "<|turn>user\n"
    "next<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "schema_and_args/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    "sys with "
    'spaces<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "hi<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_call>call:noop{}<tool_call|><|tool_response>response:search{value:<|"|>r1 '
    '"quoted"<|"|>}<tool_response|><|tool_response>response:noop{value:<|"|> '
    'r2 <|"|>}<tool_response|><turn|>\n'
    "<|turn>user\n"
    "next<turn|>\n"
    "<|turn>model\n",
    "thought_in_content/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    "visible<turn|>\n"
    "<|turn>user\n"
    "again<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "thought_in_content/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    "visible<turn|>\n"
    "<|turn>user\n"
    "again<turn|>\n"
    "<|turn>model\n",
    "tool_resp_no_id/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:search{value:<|"|>only '
    'name<|"|>}<tool_response|>',
    "tool_resp_no_id/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:search{value:<|"|>only '
    'name<|"|>}<tool_response|><|channel>thought\n',
    "tool_resp_unknown/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:unknown{value:<|"|>anon<|"|>}<tool_response|>',
    "tool_resp_unknown/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "q<turn|>\n"
    "<|turn>model\n"
    '<|tool_call>call:search{big:1e+21,filters:{lang:<|"|>zh<|"|>,z:[1,<|"|>two<|"|>,{k:false}]},flag:true,limit:3,none:null,query:<|"|>x '
    'y<|"|>,score:0.25,small:1.5e-07,tags:[]}<tool_call|><|tool_response>response:unknown{value:<|"|>anon<|"|>}<tool_response|><|channel>thought\n',
    "unit_sep_whitespace/think=False": "<bos><|turn>system\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "\x1c"
    "keep\x1f<turn|>\n"
    "<|turn>model\n"
    "<|channel>thought\n"
    "<channel|>",
    "unit_sep_whitespace/think=omitted": "<bos><|turn>system\n"
    "<|think|>\n"
    '<|tool>declaration:search{description:<|"|>Search the '
    'index.<|"|>,parameters:{properties:{filters:{description:<|"|>Nested<|"|>,properties:{lang:{type:<|"|>STRING<|"|>},since:{type:<|"|>STRING<|"|>}},required:[<|"|>lang<|"|>],type:<|"|>OBJECT<|"|>},flag:{type:<|"|>BOOLEAN<|"|>},limit:{type:<|"|>INTEGER<|"|>},loose:{properties:{},type:<|"|>OBJECT<|"|>},maybe:{type:<|"|>[\'STRING\', '
    '\'INTEGER\']<|"|>},mode:{enum:[<|"|>fast<|"|>,<|"|>exact<|"|>,<|"|>3<|"|>],type:<|"|>STRING<|"|>},query:{description:<|"|>What '
    "to "
    'find<|"|>,type:<|"|>STRING<|"|>},rows:{items:{properties:{id:{type:<|"|>INTEGER<|"|>},label:{description:<|"|>x<|"|>,type:<|"|>STRING<|"|>}},required:[<|"|>id<|"|>],type:<|"|>OBJECT<|"|>},type:<|"|>ARRAY<|"|>},score:{description:<|"|>Threshold<|"|>,type:<|"|>[\'NUMBER\', '
    '\'NULL\']<|"|>},tags:{items:{enum:[<|"|>a<|"|>,<|"|>b<|"|>],type:<|"|>STRING<|"|>},type:<|"|>ARRAY<|"|>}},required:[<|"|>query<|"|>,<|"|>filters<|"|>],type:<|"|>OBJECT<|"|>}}<tool|><|tool>declaration:noop{description:<|"|><|"|>,parameters:{type:<|"|>OBJECT<|"|>}}<tool|><turn|>\n'
    "<|turn>user\n"
    "\x1c"
    "keep\x1f<turn|>\n"
    "<|turn>model\n",
}
