import json

from agent_loop.client import call
from agent_loop.messages import answer_of, assistant_turn, tool_result, uses
from agent_loop.reporting import report

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
    final = None
    for turn in range(1, 6):
        body, elapsed = call(messages, tools=tools)
        message, calls = report(body, elapsed, f"turn {turn}  ")
        messages.append(assistant_turn(message))
        if not calls:
            final = message
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
    ok = seen[:2] == ["get_capital", "get_population"] and uses(answer_of(final), "13960000")
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
    final = None
    for turn in range(1, 5):
        body, elapsed = call(messages, tools=tools)
        message, calls = report(body, elapsed, f"turn {turn}  ")
        messages.append(assistant_turn(message))
        if not calls:
            final = message
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
    ok = (
        len(attempts) >= 2
        and attempts[1] != attempts[0]
        and uses(answer_of(final), "2600000")
    )
    print(f"  => {'PASS' if ok else 'FAIL'}: adapted after the error, attempts={attempts}")
