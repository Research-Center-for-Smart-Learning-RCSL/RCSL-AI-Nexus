import json
import os
import subprocess
import sys
import tempfile

from harness_parts.extraction import extract_block

_RUNNER = r'''
import json, signal, sys, traceback

_RESULTS_PATH = sys.argv[1]
_CHECKS = json.loads(sys.argv[2])
_results = []


class _Budget(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Budget("check exceeded its budget")


signal.signal(signal.SIGALRM, _on_alarm)

_load_error = None
try:
    exec(compile(open(sys.argv[3]).read(), "<candidate>", "exec"), globals())
    exec(compile(open(sys.argv[4]).read(), "<setup>", "exec"), globals())
except BaseException:
    _load_error = traceback.format_exc(limit=3)[-400:]

if _load_error is not None:
    for _name, _src, _budget in _CHECKS:
        _results.append([_name, False, "did not load: " + _load_error])
else:
    for _name, _src, _budget in _CHECKS:
        signal.setitimer(signal.ITIMER_REAL, float(_budget))
        try:
            exec(compile(_src, "<check:%s>" % _name, "exec"), globals())
            _results.append([_name, True, ""])
        except BaseException as _exc:
            _results.append([_name, False, ("%s: %s" % (type(_exc).__name__, _exc))[:300]])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

with open(_RESULTS_PATH, "w") as _fh:
    json.dump(_results, _fh)
'''


def score_code_task(task: dict, candidate_text: str) -> tuple[float, list]:
    """Run the candidate's code against the task's checks in a subprocess.

    Returns (fraction of checks passed, per-check detail). Each check carries its
    own in-process alarm, so a timing check that blows its budget does not take
    the correctness checks beside it down.
    """
    checks = task["checks"]
    if task.get("kind_hint") == "json":
        payload = extract_block(candidate_text, want="json") or ""
        source = "_PAYLOAD = " + repr(payload) + "\n"
    else:
        source = extract_block(candidate_text, want="python") or ""

    with tempfile.TemporaryDirectory(prefix="modeleval-") as tmp:
        cand = os.path.join(tmp, "candidate.py")
        setup = os.path.join(tmp, "setup.py")
        runner = os.path.join(tmp, "runner.py")
        out = os.path.join(tmp, "results.json")
        with open(cand, "w") as fh:
            fh.write(source)
        with open(setup, "w") as fh:
            fh.write(task.get("setup", ""))
        with open(runner, "w") as fh:
            fh.write(_RUNNER)

        wall = sum(float(c[2]) for c in checks) + 120
        try:
            subprocess.run(
                [sys.executable, runner, out, json.dumps(checks), cand, setup],
                cwd=tmp, timeout=wall, capture_output=True,
            )
        except subprocess.TimeoutExpired:
            return 0.0, [[c[0], False, "subprocess wall clock exceeded"] for c in checks]

        if not os.path.exists(out):
            return 0.0, [[c[0], False, "runner produced no result"] for c in checks]
        with open(out) as fh:
            detail = json.load(fh)

    passed = sum(1 for _, ok, _ in detail if ok)
    return passed / len(checks), detail
