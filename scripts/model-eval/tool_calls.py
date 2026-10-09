"""Does a model call the right tool with the right arguments? (#27)

    python3 tool_calls.py qwen2.5:7b=32768 qwen2.5:7b-tools=32768 --samples 5

Written to measure #27: Ollama renders a template's `{{ .Function }}` as a Go
struct, so qwen2.5 saw `{read_file Read a file. {object <nil> <nil> [path] ...}}`
instead of JSON with field names. The cases are built so that the names
matter: several tools with overlapping purposes, optional arguments that must
be left out or filled in, enums, and a request that needs no tool at all.

Each case is sent once per model through `/api/chat` with `tools` at
temperature 0 and a fixed seed, which repeats on one runtime version, and
`--samples N` more times at temperature 0.7 with seeds 1..N, which shows a
difference the greedy run can be too coarse to.
A case passes when the calls made are exactly the expected ones: the function
names, and for each the expected arguments with equal values (string
comparison is case-insensitive). Extra arguments fail a case only when they
are not declared by the tool.

Requests carry each model's production `num_ctx` and `keep_alive: -1`, so a
resident model is not reloaded. Standard library only, like the rest of this
directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _s(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def _i(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


FILES = [
    _tool(
        "read_file",
        "Read a file from the repository.",
        {"repo_path": _s("Path from the repo root")},
        ["repo_path"],
    ),
    _tool(
        "search_code",
        "Search the repository for a regular expression.",
        {"pattern": _s("Regular expression"), "max_results": _i("Upper bound on matches")},
        ["pattern"],
    ),
    _tool(
        "list_directory",
        "List the entries of a directory.",
        {"dir_path": _s("Directory from the repo root"), "include_hidden": {"type": "boolean"}},
        ["dir_path"],
    ),
]
WEATHER = [
    _tool(
        "get_forecast",
        "Weather forecast for a city.",
        {
            "city": _s("City name"),
            "days_ahead": _i("0 is today"),
            "unit": _s("Temperature unit", enum=["celsius", "fahrenheit"]),
        },
        ["city"],
    ),
    _tool(
        "get_air_quality",
        "Current air quality index for a city.",
        {"city": _s("City name")},
        ["city"],
    ),
]
CALENDAR = [
    _tool(
        "create_event",
        "Create a calendar event.",
        {
            "title": _s("Event title"),
            "start_iso": _s("Start, ISO 8601"),
            "duration_minutes": _i("Length in minutes"),
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "Emails"},
        },
        ["title", "start_iso"],
    ),
    _tool(
        "cancel_event",
        "Cancel a calendar event by its id.",
        {"event_id": _s("The event id"), "notify": {"type": "boolean"}},
        ["event_id"],
    ),
    _tool(
        "find_free_slot",
        "Find the next free slot of a given length.",
        {"duration_minutes": _i("Length in minutes"), "after_iso": _s("Earliest start")},
        ["duration_minutes"],
    ),
]
DATA = [
    _tool(
        "run_sql",
        "Run a read-only SQL query against the analytics database.",
        {"query": _s("SQL text"), "row_limit": _i("Maximum rows returned")},
        ["query"],
    ),
    _tool(
        "convert_currency",
        "Convert an amount between currencies.",
        {"amount": {"type": "number"}, "from_code": _s("ISO 4217"), "to_code": _s("ISO 4217")},
        ["amount", "from_code", "to_code"],
    ),
]


@dataclass(frozen=True)
class Case:
    name: str
    prompt: str | list[dict[str, Any]]
    """A user message, or a whole conversation (for follow-ups after a result)."""
    tools: list[dict]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    """Expected calls in order; empty means the model should answer directly.
    A value may be a predicate, for answers with more than one right form."""
    forbidden: tuple[str, ...] = ()
    """Optional arguments the request gives no value for: inventing one fails."""


CASES = [
    Case(
        "read",
        "Show me what's in backend/app/main.py.",
        FILES,
        [("read_file", {"repo_path": "backend/app/main.py"})],
    ),
    Case(
        "search",
        "Find where 'def route_chat' is defined.",
        FILES,
        [("search_code", {"pattern": lambda v: isinstance(v, str) and "route_chat" in v})],
    ),
    Case(
        "search_limit",
        "Search for TODO, but give me at most 5 hits.",
        FILES,
        [("search_code", {"pattern": "TODO", "max_results": 5})],
    ),
    Case(
        "list",
        "What files are in the docs folder?",
        FILES,
        [("list_directory", {"dir_path": "docs"})],
    ),
    Case(
        "list_hidden",
        "List everything in the repo root, including dotfiles.",
        FILES,
        [("list_directory", {"dir_path": ".", "include_hidden": True})],
    ),
    Case("files_none", "What does the acronym API stand for?", FILES),
    Case(
        "forecast",
        "What's the weather in Taipei today?",
        WEATHER,
        [("get_forecast", {"city": "Taipei"})],
    ),
    Case(
        "forecast_unit",
        "Give me the forecast for Boston three days from now, in fahrenheit.",
        WEATHER,
        [("get_forecast", {"city": "Boston", "days_ahead": 3, "unit": "fahrenheit"})],
    ),
    Case(
        "air",
        "How's the air quality in Delhi right now?",
        WEATHER,
        [("get_air_quality", {"city": "Delhi"})],
    ),
    Case(
        "two_cities",
        "Compare today's weather in Tokyo and Osaka.",
        WEATHER,
        [("get_forecast", {"city": "Tokyo"}), ("get_forecast", {"city": "Osaka"})],
    ),
    Case("weather_none", "Why is the sky blue?", WEATHER),
    Case(
        "create",
        "Book 'Design review' on 2026-10-12 at 14:00 for 45 minutes.",
        CALENDAR,
        [("create_event", {"title": "Design review", "duration_minutes": 45})],
    ),
    Case(
        "cancel",
        "Cancel event ev_8812 and don't notify anyone.",
        CALENDAR,
        [("cancel_event", {"event_id": "ev_8812", "notify": False})],
    ),
    Case(
        "free",
        "When is my next free 30-minute slot?",
        CALENDAR,
        [("find_free_slot", {"duration_minutes": 30})],
    ),
    Case(
        "sql",
        "How many rows are in the usage_records table?",
        DATA,
        [("run_sql", {})],
    ),
    Case(
        "sql_limit",
        "Show me the first 10 rows of the api_keys table.",
        DATA,
        [("run_sql", {"row_limit": 10})],
    ),
    Case(
        "currency",
        "Convert 250 euros to Japanese yen.",
        DATA,
        [("convert_currency", {"amount": 250, "from_code": "EUR", "to_code": "JPY"})],
    ),
    Case("data_none", "Say hello in French.", DATA),
    Case(
        "mixed",
        "Read README.md and also tell me Taipei's air quality.",
        FILES + WEATHER,
        [("read_file", {"repo_path": "README.md"}), ("get_air_quality", {"city": "Taipei"})],
    ),
    Case(
        "mixed_pick",
        "Convert 100 USD to TWD.",
        FILES + WEATHER + CALENDAR + DATA,
        [("convert_currency", {"amount": 100, "from_code": "USD", "to_code": "TWD"})],
    ),
]

DECOYS = [
    _tool(
        "read_file_metadata",
        "Size and modification time of a file, not its contents.",
        {"repo_path": _s("Path")},
        ["repo_path"],
    ),
    _tool(
        "get_climate_normals",
        "Thirty-year climate averages for a city, not a forecast.",
        {"city": _s("City")},
        ["city"],
    ),
    _tool(
        "create_task",
        "Create a to-do item (not a calendar event).",
        {"title": _s("Task title"), "due_iso": _s("Due date")},
        ["title"],
    ),
    _tool(
        "explain_sql",
        "Show the query plan for SQL without running it.",
        {"query": _s("SQL text")},
        ["query"],
    ),
    _tool(
        "get_exchange_rate",
        "The rate between two currencies, without converting an amount.",
        {"from_code": _s("ISO 4217"), "to_code": _s("ISO 4217")},
        ["from_code", "to_code"],
    ),
]
TICKETS = [
    _tool(
        "open_ticket",
        "Open an issue in the tracker.",
        {
            "title": _s("One-line summary"),
            "severity": _s("How bad", enum=["low", "medium", "high", "critical"]),
            "labels": {"type": "array", "items": {"type": "string"}},
            "assignee": {
                "type": "object",
                "properties": {"login": _s("Tracker username"), "team": _s("Team name")},
                "required": ["login"],
            },
        },
        ["title", "severity"],
    ),
]
EVERYTHING = FILES + WEATHER + CALENDAR + DATA + DECOYS + TICKETS


def _taipei(v: Any) -> bool:
    return isinstance(v, str) and ("taipei" in v.casefold() or "台北" in v or "臺北" in v)


def _after_result(
    question: str, call: str, arguments: dict[str, Any], result: str
) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": question},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": call, "arguments": arguments}}],
        },
        {"role": "tool", "content": result, "tool_name": call},
    ]


CASES += [
    Case(
        "decoy_read",
        "Open backend/pyproject.toml and show me its contents.",
        EVERYTHING,
        [("read_file", {"repo_path": "backend/pyproject.toml"})],
    ),
    Case(
        "decoy_meta",
        "When was backend/pyproject.toml last modified?",
        EVERYTHING,
        [("read_file_metadata", {"repo_path": "backend/pyproject.toml"})],
    ),
    Case(
        "decoy_forecast",
        "Will it rain in Kaohsiung tomorrow?",
        EVERYTHING,
        [("get_forecast", {"city": "Kaohsiung", "days_ahead": 1})],
    ),
    Case(
        "decoy_normals",
        "What is Kaohsiung's average July temperature historically?",
        EVERYTHING,
        [("get_climate_normals", {"city": "Kaohsiung"})],
    ),
    Case(
        "decoy_task",
        "Add a to-do: renew the TLS certificate.",
        EVERYTHING,
        [("create_task", {"title": lambda v: isinstance(v, str) and "tls" in v.casefold()})],
    ),
    Case(
        "decoy_explain",
        "Show me the query plan for SELECT * FROM nodes, but don't run it.",
        EVERYTHING,
        [("explain_sql", {})],
    ),
    Case(
        "decoy_rate",
        "What's the current USD to TWD rate?",
        EVERYTHING,
        [("get_exchange_rate", {"from_code": "USD", "to_code": "TWD"})],
    ),
    Case(
        "nested",
        "Open a high-severity ticket 'Gateway 503 after Ollama restart', labels runtime "
        "and ops, assign to login mlin on team infra.",
        EVERYTHING,
        [
            (
                "open_ticket",
                {
                    "severity": "high",
                    "labels": lambda v: (
                        isinstance(v, list) and {x.casefold() for x in v} == {"runtime", "ops"}
                    ),
                    "assignee": lambda v: (
                        isinstance(v, dict)
                        and str(v.get("login", "")).casefold() == "mlin"
                        and str(v.get("team", "")).casefold() == "infra"
                    ),
                },
            )
        ],
    ),
    Case(
        "no_invented_optional",
        "Open a low-severity ticket titled 'Typo in README'.",
        EVERYTHING,
        [("open_ticket", {"severity": "low"})],
        forbidden=("assignee",),
    ),
    Case(
        "zh_forecast",
        "幫我查台北明天的天氣，用攝氏。",
        EVERYTHING,
        [("get_forecast", {"city": _taipei, "days_ahead": 1, "unit": "celsius"})],
    ),
    Case(
        "zh_cancel",
        "請取消行程 ev_42，並通知參加者。",
        EVERYTHING,
        [("cancel_event", {"event_id": "ev_42", "notify": True})],
    ),
    Case("zh_none", "用一句話解釋什麼是 API 金鑰。", EVERYTHING),
    Case(
        "followup_next",
        _after_result(
            "What's in docs/ and then read the first markdown file?",
            "list_directory",
            {"dir_path": "docs"},
            '["PROGRESS.md", "images/", "security.md"]',
        ),
        FILES,
        [("read_file", {"repo_path": "docs/PROGRESS.md"})],
    ),
    Case(
        "followup_answer",
        _after_result(
            "How many keys are there?",
            "run_sql",
            {"query": "SELECT count(*) FROM api_keys"},
            '[{"count": 17}]',
        ),
        DATA,
    ),
]


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        HOST + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - local runtime
        return json.loads(response.read())


def _same(expected: Any, got: Any) -> bool:
    if callable(expected):
        return bool(expected(got))
    if isinstance(expected, str) and isinstance(got, str):
        return expected.casefold() == got.casefold()
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got
    if isinstance(expected, (int, float)) and isinstance(got, (int, float, str)):
        try:
            return float(expected) == float(got)
        except ValueError:
            return False
    return bool(expected == got)


def judge(case: Case, message: dict[str, Any]) -> tuple[bool, str]:
    calls = [c["function"] for c in message.get("tool_calls") or []]
    if not case.calls:
        return (not calls, "answered directly" if not calls else f"called {calls}")
    if len(calls) != len(case.calls):
        return False, f"{len(calls)} calls: {calls or message.get('content', '')[:120]!r}"
    declared = {
        t["function"]["name"]: t["function"]["parameters"]["properties"] for t in case.tools
    }
    for (name, expected), call in zip(case.calls, calls, strict=True):
        arguments = call.get("arguments") or {}
        if call.get("name") != name:
            return False, f"called {call.get('name')} not {name}"
        unknown = set(arguments) - set(declared[name])
        if unknown:
            return False, f"undeclared arguments {sorted(unknown)}"
        invented = set(arguments) & set(case.forbidden)
        if invented:
            return False, f"invented {sorted(invented)}"
        for key, value in expected.items():
            if not _same(value, arguments.get(key)):
                return False, f"{name}.{key} = {arguments.get(key)!r}"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="+", help="ref=num_ctx (the production context)")
    parser.add_argument(
        "--samples",
        type=int,
        default=0,
        help="also run each case this many times at temperature 0.7, seeds 1..N",
    )
    args = parser.parse_args()
    with urllib.request.urlopen(HOST + "/api/version", timeout=10) as response:  # noqa: S310
        version = json.loads(response.read())["version"]
    # (temperature, seed): one greedy run, then the sampled ones.
    runs = [(0.0, 42)] + [(0.7, seed) for seed in range(1, args.samples + 1)]
    totals: dict[tuple[str, bool], list[int]] = {}
    for spec in args.models:
        ref, _, ctx = spec.partition("=")
        for temperature, seed in runs:
            for case in CASES:
                reply = _post(
                    "/api/chat",
                    {
                        "model": ref,
                        "messages": [{"role": "user", "content": case.prompt}]
                        if isinstance(case.prompt, str)
                        else case.prompt,
                        "tools": case.tools,
                        "stream": False,
                        "keep_alive": -1,
                        "options": {"num_ctx": int(ctx), "temperature": temperature, "seed": seed},
                    },
                )
                ok, why = judge(case, reply["message"])
                tally = totals.setdefault((ref, temperature > 0), [0, 0])
                tally[0] += ok
                tally[1] += 1
                record = {"ollama": version, "model": ref, "temperature": temperature, "seed": seed}
                print(json.dumps({**record, "case": case.name, "pass": ok, "why": why}), flush=True)
    for (ref, sampled), (passed, total) in totals.items():
        kind = "sampled" if sampled else "greedy"
        print(f"{ref} {kind}: {passed}/{total}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
