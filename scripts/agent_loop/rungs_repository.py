import json

from agent_loop.client import call
from agent_loop.messages import assistant_turn, tool_result
from agent_loop.reporting import report

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
    "tests/test_calc.py": (
        "from src.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    ),
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
    ran_after_fix = (
        "run_tests" in trace[trace.index("write_file") :] if "write_file" in trace else False
    )
    print(f"  trace: {trace}")
    print(f"  src/calc.py now: {repo.get('src/calc.py')!r}")
    outcome = "PASS" if fixed and ran_after_fix else "FAIL"
    print(f"  => {outcome}: fixed the bug and re-ran the tests")
