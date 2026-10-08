"""Gemma 4's prompt format, rendered the way the runtime renders it.

Ported from Ollama's `model/renderers/gemma4.go` (v0.33.2), Copyright (c)
Ollama, MIT licensed; the notice is reproduced in ATTRIBUTIONS.md.

Gemma 4's GGUF carries no chat template. Ollama renders it with a renderer
built into the runtime, `model/renderers/gemma4.go` (v0.33.2), so there was
nothing in the weights for the counter to execute, and it fell back to ChatML:
a different format, which rendered tool calls as empty turns (#24, #28). This
is a port of that renderer, kept to what the gateway can send: text content,
tools, tool calls and tool results. Images are never sent through the counter.

It renders the same payload the adapter sends (`message_payload`,
`tool_payload`), and it is held to the runtime by bytes, not by counts:
`scripts/runtime-probes/render_diff.py` compares its output with the runtime's
own `_debug_render_only` rendering, and `test_gemma4_renderer.py` pins cases
taken from that comparison. Go's formatting is reproduced where it differs from
Python's (whitespace trimming, number formatting, sorted keys).

Thinking is a parameter, with the runtime's meaning: `think=False` renders it
off, and `None` (the field omitted, which is what the gateway sends when its
thinking is on) or `True` render it on. Measured 2026-10-08: an omitted field
renders `<|think|>` on gemma4, so "omitted" is not "off".

One place deliberately differs from the runtime, in the direction of counting
more, never less:

- The small/large variant. Ollama picks it from the model's name or declared
  size and defaults to small; this defaults to large when neither decides,
  because large adds an empty thought block and so can only over-count.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

Q = '<|"|>'
"""Gemma 4's string delimiter."""

_GO_SPACE = " \t\n\v\f\r\x85\xa0                　"
"""Go's `unicode.IsSpace`. Python's `str.strip()` also strips U+001C-U+001F,
which Go keeps, so `strings.TrimSpace` is reproduced explicitly."""

_SCHEMA_STANDARD_KEYS = frozenset({"description", "type", "properties", "required", "nullable"})


def _trim(text: str) -> str:
    return text.strip(_GO_SPACE)


def renderer_variant(ref: str) -> str:
    """`small` or `large`, as Ollama's `resolveGemma4Renderer` decides by name.

    Undecided falls back to `large` (Ollama: `small`), which over-counts.
    """
    lower = ref.lower()
    if "e2b" in lower or "e4b" in lower:
        return "small"
    return "large"


class Gemma4Renderer:
    """Renders an Ollama chat payload as Gemma 4's prompt text.

    Exposes `render(messages=..., tools=..., add_generation_prompt=...)`, the
    same call the counter makes on a Jinja template, so it can stand in for one.
    """

    def __init__(self, *, large: bool) -> None:
        self._empty_block_on_nothink = large

    def render(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        add_generation_prompt: bool = True,
        think: bool | None = None,
    ) -> str:
        del add_generation_prompt  # the runtime always appends the generation prompt
        tools = list(tools or [])
        has_think = think is not False
        out: list[str] = ["<bos>"]

        has_system = bool(messages) and messages[0].get("role") in ("system", "developer")
        system_message = (messages[0].get("content") or "") if has_system else ""
        loop = list(messages[1:] if has_system else messages)

        if has_system or tools or has_think:
            out.append("<|turn>system\n")
            if has_think:
                out.append("<|think|>\n")
            if system_message:
                out.append(_trim(system_message))
            for tool in tools:
                out.append(_tool_declaration(tool.get("function") or {}))
            out.append("<turn|>\n")

        last_user = max((i for i, m in enumerate(loop) if m.get("role") == "user"), default=-1)
        prev_type = ""
        prev_non_tool_role = ""
        for i, message in enumerate(loop):
            role_in = message.get("role")
            if role_in == "tool":
                continue
            prev_type = ""
            role = "model" if role_in == "assistant" else role_in
            calls = list(message.get("tool_calls") or [])
            content = message.get("content") or ""

            if not (role == "model" and prev_non_tool_role == "assistant"):
                out.append(f"<|turn>{role}\n")

            thinking = message.get("thinking") or ""
            if role_in == "assistant" and thinking and i > last_user:
                out.append(f"<|channel>thought\n{thinking}\n<channel|>")

            if calls:
                for call in calls:
                    out.append(_tool_call(call.get("function") or {}))
                prev_type = "tool_call"

            responses_emitted = False
            if calls:
                k = i + 1
                while k < len(loop) and loop[k].get("role") == "tool":
                    name = _tool_response_name(loop[k], calls)
                    value = _arg_value(loop[k].get("content") or "")
                    out.append(f"<|tool_response>response:{name}{{value:{value}}}<tool_response|>")
                    responses_emitted = True
                    prev_type = "tool_response"
                    k += 1

            if role == "model":
                had_content = False
                if content:
                    content = _strip_thinking(content)
                    out.append(content)
                    had_content = _trim(content) != ""
            else:
                out.append(_trim(content))
                had_content = _trim(content) != ""

            next_role = next((m.get("role") for m in loop[i + 1 :] if m.get("role") != "tool"), "")
            continues = (
                role == "model" and next_role == "assistant" and (not calls or responses_emitted)
            )
            if prev_type == "tool_call" and not responses_emitted:
                out.append("<|tool_response>")
            elif not continues and not (responses_emitted and not had_content and next_role == ""):
                out.append("<turn|>\n")
            prev_non_tool_role = role_in or ""

        if prev_type not in ("tool_response", "tool_call"):
            out.append("<|turn>model\n")
            if self._empty_block_on_nothink and not has_think:
                out.append("<|channel>thought\n<channel|>")
        elif prev_type == "tool_response" and has_think:
            out.append("<|channel>thought\n")
        return "".join(out)


def _strip_thinking(text: str) -> str:
    result: list[str] = []
    while True:
        start = text.find("<|channel>")
        if start == -1:
            result.append(text)
            break
        result.append(text[:start])
        end = text.find("<channel|>", start)
        if end == -1:
            break
        text = text[end + len("<channel|>") :]
    return _trim("".join(result))


def _tool_response_name(message: Mapping[str, Any], calls: Sequence[Mapping[str, Any]]) -> str:
    name = message.get("tool_name") or "unknown"
    call_id = message.get("tool_call_id")
    if call_id:
        for call in calls:
            if call.get("id") == call_id:
                return str((call.get("function") or {}).get("name", name))
    return str(name)


def _go_g(value: float) -> str:
    """Go's `%v` for a float64: `strconv.FormatFloat(v, 'g', -1, 64)`.

    The shortest round-tripping digits (Python's `repr` finds the same ones),
    in exponent form when the exponent is below -4 or at least 6, which is
    where Go switches and Python does not: `1234567.5` is `1.2345675e+06` in
    Go and `1234567.5` in Python (review on #29).
    """
    if value == 0:
        return "-0" if math.copysign(1.0, value) < 0 else "0"
    sign = "-" if value < 0 else ""
    digits_text, _, exp_text = repr(abs(value)).partition("e")
    whole, _, frac = digits_text.partition(".")
    digits = (whole + frac).lstrip("0")
    point = len(whole) + (int(exp_text) if exp_text else 0)  # digits before the point
    leading_zeros = len(whole + frac) - len((whole + frac).lstrip("0"))
    point -= leading_zeros
    digits = digits.rstrip("0") or "0"
    exponent = point - 1
    if exponent < -4 or exponent >= 6:
        mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        return f"{sign}{mantissa}e{'-' if exponent < 0 else '+'}{abs(exponent):02d}"
    if point <= 0:
        return f"{sign}0.{'0' * -point}{digits}"
    if point >= len(digits):
        return f"{sign}{digits}{'0' * (point - len(digits))}"
    return f"{sign}{digits[:point]}.{digits[point:]}"


_INT64_MAX = 2**63 - 1
_INT64_MIN = -(2**63)


def _go_float(value: float) -> str:
    """`if v == float64(int64(v)) { %d } else { %v }`, as `formatArgValue` does.

    The conversion is Go on arm64 (this host): out-of-range values saturate to
    the int64 limits, so only exactly +/-2**63 round-trip, and everything else
    beyond int64 falls through to `%v`: `1e19` is `1e+19` (review on #29).
    """
    if not math.isfinite(value):
        return _go_g(value)
    if -(2.0**63) <= value < 2.0**63:
        as_int = int(value)
    else:
        as_int = _INT64_MAX if value > 0 else _INT64_MIN
    if float(as_int) == value:
        return str(as_int)
    return _go_g(value)


def _go_v(value: Any) -> str:
    """Go's `%v` for a JSON-decoded value; numbers decode as float64."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "<nil>"
    if isinstance(value, int | float):
        return _go_g(float(value))
    return str(value)


def _arg_value(value: Any) -> str:
    """`formatArgValue`: tool-call arguments and tool results."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f"{Q}{value}{Q}"
    if isinstance(value, int | float):
        return _go_float(float(value))
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{k}:{_arg_value(value[k])}" for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_arg_value(v) for v in value) + "]"
    return str(value)


def _tool_call(function: Mapping[str, Any]) -> str:
    arguments = function.get("arguments") or {}
    body = ",".join(f"{k}:{_arg_value(arguments[k])}" for k in sorted(arguments))
    return f"<|tool_call>call:{function.get('name', '')}{{{body}}}<tool_call|>"


def _schema_value(value: Any) -> str:
    """`formatSchemaValue`: like arguments, but map keys are delimited too."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f"{Q}{value}{Q}"
    if isinstance(value, int | float):
        return _go_float(float(value))
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{Q}{k}{Q}:{_schema_value(value[k])}" for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_schema_value(v) for v in value) + "]"
    return str(value)


def _type_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.upper()]
    if isinstance(value, list):
        return [v.upper() for v in value if isinstance(v, str)]
    return []


def _upstream_type(types: Sequence[str]) -> str:
    """A multi-type union becomes the *string* "['STRING', 'NULL']", as upstream."""
    if len(types) == 1:
        return types[0]
    return "[" + ", ".join(f"'{t.upper()}'" for t in types) + "]"


def _is_bare_type(branch: Any) -> bool:
    """`isBareTypeOnlyToolProperty`, on the fields Ollama decodes.

    Ollama decodes a branch into `api.ToolProperty` first, which drops fields
    it does not model (`title`, `default`, ...) and reads an absent and an
    empty description alike, so `{"type": "string", "description": "",
    "title": "x"}` is still a bare type branch upstream (review on #29).
    """
    if not isinstance(branch, Mapping):
        return False
    return bool(
        branch.get("type")
        and not branch.get("anyOf")
        and branch.get("items") is None
        and not branch.get("description")
        and not branch.get("enum")
        and branch.get("properties") is None
        and not branch.get("required")
    )


def _simple_any_of(prop: Mapping[str, Any]) -> list[str] | None:
    branches = prop.get("anyOf")
    if not isinstance(branches, list) or not branches:
        return None
    out: list[str] = []
    for branch in branches:
        if not _is_bare_type(branch):
            return None
        for t in [branch["type"]] if isinstance(branch["type"], str) else list(branch["type"]):
            if t not in out:
                out.append(t)
    return out or None


def _top_level(prop: Mapping[str, Any]) -> dict[str, Any]:
    """`topLevelTypedSchemaValueFromToolProperty`, from the JSON a tool carries."""
    out: dict[str, Any] = {}
    raw_type = prop.get("type")
    types = [raw_type] if isinstance(raw_type, str) else list(raw_type or [])
    if types:
        out["type"] = _upstream_type(types)
    elif (union := _simple_any_of(prop)) is not None:
        out["type"] = _upstream_type(union)
    if prop.get("description"):
        out["description"] = prop["description"]
    if prop.get("enum"):
        out["enum"] = prop["enum"]
    if prop.get("items") is not None:
        out["items"] = prop["items"]
    if isinstance(prop.get("properties"), Mapping):
        out["properties"] = {
            k: _top_level(v) for k, v in prop["properties"].items() if isinstance(v, Mapping)
        }
    if prop.get("required"):
        out["required"] = prop["required"]
    return out


def _required(names: Any) -> str:
    return "required:[" + ",".join(f"{Q}{n}{Q}" for n in names if isinstance(n, str)) + "]"


def _properties(props: Mapping[str, Any]) -> str:
    """`writeSchemaProperties`."""
    parts: list[str] = []
    for name in sorted(props):
        if name in _SCHEMA_STANDARD_KEYS:
            continue
        prop = props[name]
        if not isinstance(prop, Mapping):
            continue
        fields: list[str] = []
        if isinstance(prop.get("description"), str) and prop["description"]:
            fields.append(f"description:{Q}{prop['description']}{Q}")
        types = _type_names(prop.get("type"))
        type_name = types[0] if types else ""
        if type_name == "STRING" and isinstance(prop.get("enum"), list) and prop["enum"]:
            fields.append("enum:[" + ",".join(f"{Q}{_go_v(v)}{Q}" for v in prop["enum"]) + "]")
        if type_name == "ARRAY" and isinstance(prop.get("items"), Mapping) and prop["items"]:
            fields.append("items:{" + _items(prop["items"]) + "}")
        if prop.get("nullable") is True:
            fields.append("nullable:true")
        if type_name == "OBJECT":
            nested = prop.get("properties")
            fields.append(
                "properties:{" + _properties(nested if isinstance(nested, Mapping) else prop) + "}"
            )
            required = [r for r in prop.get("required") or [] if isinstance(r, str)]
            if required:
                fields.append(_required(required))
        if types:
            fields.append(
                f"type:{Q}{types[0]}{Q}"
                if len(types) == 1
                else "type:[" + ",".join(f"{Q}{t}{Q}" for t in types) + "]"
            )
        parts.append(f"{name}:{{" + ",".join(fields) + "}")
    return ",".join(parts)


def _items(items: Mapping[str, Any]) -> str:
    """`writeSchemaItemsSpec`."""
    parts: list[str] = []
    for key in sorted(items):
        value = items[key]
        if value is None:
            continue
        if key == "properties":
            parts.append(
                "properties:{" + (_properties(value) if isinstance(value, Mapping) else "") + "}"
            )
        elif key == "required":
            parts.append(_required(value if isinstance(value, list) else []))
        elif key == "type":
            types = _type_names(value)
            if len(types) == 1:
                parts.append(f"type:{Q}{types[0]}{Q}")
            elif types:
                parts.append("type:[" + ",".join(f"{Q}{t}{Q}" for t in types) + "]")
        else:
            parts.append(f"{key}:{_schema_value(value)}")
    return ",".join(parts)


def _tool_declaration(function: Mapping[str, Any]) -> str:
    """`renderToolDeclaration`."""
    name, description = function.get("name", ""), function.get("description", "")
    out = [f"<|tool>declaration:{name}{{description:{Q}{description}{Q}"]
    params = function.get("parameters") or {}
    properties = params.get("properties")
    param_type = params.get("type") or ""
    if properties is not None or param_type:
        fields: list[str] = []
        if isinstance(properties, Mapping) and properties:
            typed = {k: _top_level(v) for k, v in properties.items() if isinstance(v, Mapping)}
            fields.append("properties:{" + _properties(typed) + "}")
        if params.get("required"):
            fields.append(_required(params["required"]))
        if param_type:
            fields.append(f"type:{Q}{param_type.upper()}{Q}")
        out.append(",parameters:{" + ",".join(fields) + "}")
    out.append("}<tool|>")
    return "".join(out)
