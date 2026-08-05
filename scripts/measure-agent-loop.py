#!/usr/bin/env python3
"""Can a local model actually drive an agent loop?

A ladder, simplest first. Each rung isolates one thing that has to work before
the next is even meaningful, so a failure names *which* ability is missing
rather than reporting that the agent did not finish.

    NEXUS_API_KEY=nx_live_... scripts/measure-agent-loop.py 10
    NEXUS_API_KEY=nx_live_... scripts/measure-agent-loop.py all

The rungs: 1 emit a call, 2 fill an argument, 3 complete the round trip,
4 choose between two tools, 5 chain two calls, 6 decline to call when the
question needs no tool, 7 two calls in one turn, 8 recover from a tool error,
9 choose from a menu of eight, 10 the real shape — read failing tests, find
the bug, fix the source, re-run to confirm.

Environment:

    NEXUS_API_KEY      required; a key scoped to the capability below
    NEXUS_MODEL        the *capability*, not a model name (default: chat)
    NEXUS_THINK        true/false to override deliberation per request.
                       Unset asks for nothing, so the routing policy decides,
                       which is what a real client does. Set it to measure what
                       deliberation costs: an agent pays it again on every tool
                       round trip rather than once per conversation.
    NEXUS_GATEWAY      base URL. Defaults to TAILNET_IP from .env on port 8000,
                       because the gateway publishes on the tailnet address and
                       never on loopback or 0.0.0.0
    NEXUS_PROXY_SECRET  } see below; both default to reading ./secrets
    NEXUS_CLIENT_IP    an address the country filter allows (default: a TW one)

Standing in for the proxy is not optional. Under ENV=production the gateway
requires the shared-secret header and refuses to fall back to the peer address
for `X-Forwarded-For`, so a request straight from the host is a 400
`untrusted_proxy`. That is the perimeter working; this supplies both headers
the way openresty would.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

def _default_gateway() -> str:
    """`TAILNET_IP` from `.env`, not loopback.

    The gateway deliberately publishes on the tailnet address rather than
    `0.0.0.0` or `127.0.0.1` (see the README, "Two things that look like
    mistakes"), so a loopback default would fail on every real deployment and
    succeed only where `TAILNET_IP=127.0.0.1`, which is the dev-machine value
    in `.env.example`. Reading the same variable Compose reads keeps the two
    from disagreeing.
    """
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TAILNET_IP" and value.split("#")[0].strip():
                return f"http://{value.split('#')[0].strip()}:8000"
    return "http://127.0.0.1:8000"


GATEWAY = os.environ.get("NEXUS_GATEWAY", _default_gateway()).rstrip("/")
BASE = f"{GATEWAY}/v1/chat/completions"
CLIENT_IP = os.environ.get("NEXUS_CLIENT_IP", "168.95.1.1")  # Chunghwa Telecom, TW
MODEL = os.environ.get("NEXUS_MODEL", "chat")  # the capability, not a model name
THINK = {"true": True, "false": False}.get(os.environ.get("NEXUS_THINK", "").lower())
TOTALS = {"turns": 0, "seconds": 0.0, "prompt": 0, "completion": 0}


def _required(env: str, secret_file: str, what: str) -> str:
    """Resolved on first use rather than at import, so `--help` and a syntax
    check work on a machine that has neither."""
    value = os.environ.get(env)
    if value:
        return value.strip()
    path = REPO / "secrets" / secret_file
    if path.is_file():
        return path.read_text().strip()
    sys.exit(f"{what}: set {env}, or run from a checkout with secrets/{secret_file}")


def key() -> str:
    value = os.environ.get("NEXUS_API_KEY")
    if not value:
        sys.exit(
            "NEXUS_API_KEY is not set. Issue a key for the capability under test "
            "from the management UI (API keys), or see "
            "docs/runbooks/connect-an-agent-client.md. The plaintext is shown once."
        )
    return value.strip()

# --- tools ---------------------------------------------------------------

GET_TIME = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Get the current server time. Takes no arguments.",
        "parameters": {"type": "object", "properties": {}},
    },
}

GET_WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}

GET_POPULATION = {
    "type": "function",
    "function": {
        "name": "get_population",
        "description": "Get the population of a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}

CAPITAL_OF = {
    "type": "function",
    "function": {
        "name": "get_capital",
        "description": "Get the capital city of a country.",
        "parameters": {
            "type": "object",
            "properties": {"country": {"type": "string"}},
            "required": ["country"],
        },
    },
}


def call(messages, tools=None, model=MODEL, think=THINK, timeout=900):
    payload = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    if think is not None:
        payload["think"] = think
    request = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key()}",
            "Content-Type": "application/json",
            "X-Nexus-Proxy": _required(
                "NEXUS_PROXY_SECRET", "proxy_shared_secret", "the trusted-proxy secret"
            ),
            "X-Forwarded-For": CLIENT_IP,
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code}: {exc.read().decode()[:400]}")
        raise
    elapsed = time.monotonic() - started
    usage = body.get("usage") or {}
    TOTALS["turns"] += 1
    TOTALS["seconds"] += elapsed
    TOTALS["prompt"] += usage.get("prompt_tokens") or 0
    TOTALS["completion"] += usage.get("completion_tokens") or 0
    return body, elapsed


def report(body, elapsed, label=""):
    choice = body["choices"][0]
    message = choice["message"]
    calls = message.get("tool_calls") or []
    usage = body.get("usage") or {}
    print(f"  {label}[{body.get('model')}] finish_reason = {choice.get('finish_reason')!r}   {elapsed:.1f}s")
    print(f"  tokens: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
    if calls:
        for c in calls:
            fn = c["function"]
            print(f"  CALL  {fn['name']}({fn['arguments']})   id={c['id']}")
    content = (message.get("content") or "").strip()
    if content:
        print(f"  TEXT  {content[:300]}")
    return message, calls


def assistant_turn(message):
    """Replay the assistant's own turn, calls included, as an agent client must."""
    turn = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        turn["tool_calls"] = message["tool_calls"]
    return turn


def tool_result(call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


# --- the rungs -----------------------------------------------------------


def rung1():
    """Does it emit a tool call at all, when the prompt plainly asks for one?"""
    messages = [{"role": "user", "content": "What time is it right now? Use the tool."}]
    body, elapsed = call(messages, tools=[GET_TIME])
    _, calls = report(body, elapsed)
    ok = len(calls) == 1 and calls[0]["function"]["name"] == "get_current_time"
    print(f"  => {'PASS' if ok else 'FAIL'}: one call to get_current_time")


def rung2():
    """Does it fill an argument correctly from the prompt?"""
    messages = [{"role": "user", "content": "What is the weather in Taipei?"}]
    body, elapsed = call(messages, tools=[GET_WEATHER])
    _, calls = report(body, elapsed)
    ok = False
    if len(calls) == 1 and calls[0]["function"]["name"] == "get_weather":
        args = json.loads(calls[0]["function"]["arguments"])
        ok = "taipei" in str(args.get("city", "")).lower()
    print(f"  => {'PASS' if ok else 'FAIL'}: get_weather(city=Taipei)")


def rung3():
    """The round trip: does the result come back and get used?"""
    messages = [{"role": "user", "content": "What is the weather in Taipei?"}]
    body, elapsed = call(messages, tools=[GET_WEATHER])
    message, calls = report(body, elapsed, "turn 1  ")
    if not calls:
        print("  => FAIL: no call to answer")
        return
    messages.append(assistant_turn(message))
    messages.append(tool_result(calls[0]["id"], "get_weather", "31C, thunderstorms"))
    body, elapsed = call(messages, tools=[GET_WEATHER])
    message2, calls2 = report(body, elapsed, "turn 2  ")
    text = (message2.get("content") or "").lower()
    ok = not calls2 and ("31" in text or "thunder" in text)
    print(f"  => {'PASS' if ok else 'FAIL'}: final answer carries the tool result")


def rung4():
    """Two tools: does it pick the right one?"""
    messages = [{"role": "user", "content": "How many people live in Kaohsiung?"}]
    body, elapsed = call(messages, tools=[GET_WEATHER, GET_POPULATION])
    _, calls = report(body, elapsed)
    ok = len(calls) == 1 and calls[0]["function"]["name"] == "get_population"
    print(f"  => {'PASS' if ok else 'FAIL'}: chose get_population")


def rung5():
    """A chain: the second call needs the first one's answer."""
    messages = [
        {
            "role": "user",
            "content": "What is the population of the capital of Japan? "
            "Find the capital first, then look up its population.",
        }
    ]
    tools = [CAPITAL_OF, GET_POPULATION]
    seen = []
    for turn in range(1, 6):
        body, elapsed = call(messages, tools=tools)
        message, calls = report(body, elapsed, f"turn {turn}  ")
        messages.append(assistant_turn(message))
        if not calls:
            break
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"]["arguments"] or "{}")
            seen.append(name)
            if name == "get_capital":
                result = "Tokyo"
            elif str(args.get("city", "")).lower() == "tokyo":
                result = "13,960,000"
            else:
                result = f"unknown city {args.get('city')!r}"
            messages.append(tool_result(c["id"], name, result))
    text = (messages[-1].get("content") or "").lower()
    ok = seen[:2] == ["get_capital", "get_population"] and "13,9" in text.replace(" ", "")
    print(f"  => {'PASS' if ok else 'FAIL'}: chained {seen} and used the result")


def rung6():
    """Restraint: a question no tool answers must not produce a call."""
    messages = [{"role": "user", "content": "What is 17 times 4? Answer directly."}]
    body, elapsed = call(messages, tools=[GET_WEATHER, GET_POPULATION])
    message, calls = report(body, elapsed)
    ok = not calls and "68" in (message.get("content") or "")
    print(f"  => {'PASS' if ok else 'FAIL'}: no call, answered 68")



def rung7():
    """Two independent lookups in one turn: parallel calls, or two turns?

    Either is correct; what matters is that a client buffering on `index` gets
    two distinct calls rather than one whose name and arguments are both
    concatenations of the pair.
    """
    messages = [{"role": "user", "content": "Compare the weather in Taipei and Tokyo."}]
    tools = [GET_WEATHER]
    names = []
    for turn in range(1, 6):
        body, elapsed = call(messages, tools=tools)
        message, calls = report(body, elapsed, f"turn {turn}  ")
        messages.append(assistant_turn(message))
        if not calls:
            break
        for c in calls:
            args = json.loads(c["function"]["arguments"] or "{}")
            names.append(str(args.get("city", "?")))
            messages.append(tool_result(c["id"], c["function"]["name"], "24C, clear"))
    cities = {n.lower() for n in names}
    ok = {"taipei", "tokyo"} <= cities
    print(f"  => {'PASS' if ok else 'FAIL'}: looked up both, calls={names}")


def rung8():
    """Error recovery: the tool refuses, does it adapt or repeat itself?"""
    messages = [{"role": "user", "content": "What is the population of Taipei?"}]
    tools = [GET_POPULATION]
    attempts = []
    for turn in range(1, 5):
        body, elapsed = call(messages, tools=tools)
        message, calls = report(body, elapsed, f"turn {turn}  ")
        messages.append(assistant_turn(message))
        if not calls:
            break
        for c in calls:
            args = json.loads(c["function"]["arguments"] or "{}")
            attempts.append(args.get("city"))
            if len(attempts) == 1:
                # First attempt fails with an actionable message.
                messages.append(
                    tool_result(
                        c["id"],
                        "get_population",
                        'ERROR: unknown city "Taipei". Try the official name, e.g. "Taipei City".',
                    )
                )
            else:
                messages.append(tool_result(c["id"], "get_population", "2,600,000"))
    text = (messages[-1].get("content") or "")
    ok = len(attempts) >= 2 and attempts[1] != attempts[0] and "2,6" in text.replace(" ", "")
    print(f"  => {'PASS' if ok else 'FAIL'}: adapted after the error, attempts={attempts}")


FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": list(props),
            },
        },
    }
    for name, desc, props in [
        ("list_files", "List files in a directory.", {"path": {"type": "string"}}),
        ("read_file", "Read a file's contents.", {"path": {"type": "string"}}),
        (
            "write_file",
            "Overwrite a file with new contents.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
        ),
        ("run_tests", "Run the test suite.", {}),
        ("git_status", "Show the working tree status.", {}),
        ("search_code", "Search the codebase for a string.", {"query": {"type": "string"}}),
        ("delete_file", "Delete a file.", {"path": {"type": "string"}}),
        ("make_dir", "Create a directory.", {"path": {"type": "string"}}),
    ]
]

FAKE_REPO = {
    "src/calc.py": "def add(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
}


def rung9():
    """Eight tools instead of two: does selection survive a fuller menu?"""
    messages = [{"role": "user", "content": "Show me what is in the src directory."}]
    body, elapsed = call(messages, tools=FILE_TOOLS)
    _, calls = report(body, elapsed)
    ok = len(calls) == 1 and calls[0]["function"]["name"] == "list_files"
    print(f"  => {'PASS' if ok else 'FAIL'}: chose list_files out of 8")


def rung10():
    """The real shape: find a bug, fix it, confirm the tests pass.

    Multi-step, stateful, and the answer is not in the prompt: it has to read
    the failing test, read the source, notice `-` where `+` belongs, write the
    fix, and re-run. This is the rung that actually resembles a coding agent.
    """
    repo = dict(FAKE_REPO)
    messages = [
        {
            "role": "user",
            "content": "The tests are failing. Find out why, fix the source, "
            "and run the tests again to confirm. Use the tools.",
        }
    ]
    trace = []
    for turn in range(1, 13):
        body, elapsed = call(messages, tools=FILE_TOOLS)
        message, calls = report(body, elapsed, f"turn {turn}  ")
        messages.append(assistant_turn(message))
        if not calls:
            break
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"]["arguments"] or "{}")
            trace.append(name)
            if name == "list_files":
                result = "\n".join(repo)
            elif name == "read_file":
                result = repo.get(args.get("path", ""), "ERROR: no such file")
            elif name == "write_file":
                repo[args["path"]] = args["content"]
                result = "written"
            elif name == "run_tests":
                fixed = "a + b" in repo.get("src/calc.py", "")
                result = (
                    "1 passed"
                    if fixed
                    else "FAILED tests/test_calc.py::test_add - assert -1 == 5"
                )
            elif name == "search_code":
                hits = [p for p, t in repo.items() if args.get("query", "") in t]
                result = "\n".join(hits) or "no matches"
            elif name == "git_status":
                result = "modified: src/calc.py"
            else:
                result = "ok"
            messages.append(tool_result(c["id"], name, result))
    fixed = "a + b" in repo.get("src/calc.py", "")
    ran_after_fix = "run_tests" in trace[trace.index("write_file") :] if "write_file" in trace else False
    print(f"  trace: {trace}")
    print(f"  src/calc.py now: {repo.get('src/calc.py')!r}")
    print(f"  => {'PASS' if fixed and ran_after_fix else 'FAIL'}: fixed the bug and re-ran the tests")


RUNGS = {
    1: rung1,
    2: rung2,
    3: rung3,
    4: rung4,
    5: rung5,
    6: rung6,
    7: rung7,
    8: rung8,
    9: rung9,
    10: rung10,
}


def run(which: int) -> None:
    for field in TOTALS:
        TOTALS[field] = type(TOTALS[field])()
    print(f"--- rung {which}   model={MODEL}  think={THINK} ---")
    RUNGS[which]()
    print(
        f"  TOTAL {TOTALS['turns']} turns  {TOTALS['seconds']:.1f}s  "
        f"prompt={TOTALS['prompt']}  completion={TOTALS['completion']}"
    )


def main(argv: list[str]) -> None:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        sys.exit(__doc__)
    if argv[1] == "all":
        for which in sorted(RUNGS):
            run(which)
            print()
        return
    try:
        which = int(argv[1])
    except ValueError:
        sys.exit(f"not a rung: {argv[1]!r}. Give 1..{max(RUNGS)} or 'all'.")
    if which not in RUNGS:
        sys.exit(f"no rung {which}. Give 1..{max(RUNGS)} or 'all'.")
    run(which)


if __name__ == "__main__":
    main(sys.argv)
