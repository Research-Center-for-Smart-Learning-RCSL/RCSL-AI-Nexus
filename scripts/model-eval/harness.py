"""Runner and scorer for the task set in tasks.py.

Section 5 of docs/model-evaluation.md is implemented here, item by item:

  deliberation off      think=False on every request, and recorded per sample
  truncation != wrong   done_reason == "length" with no extractable answer
                        returns no result; it is never scored as a zero
  generous budget       NUM_PREDICT is several times the longest expected answer
  quantisation matched  the caller passes q8 tags only; recorded per sample
  order rotated         see run.py
  depth recorded        prompt_eval_count and num_ctx travel with every figure
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
NUM_CTX = 16384
NUM_PREDICT = 4096
HTTP_TIMEOUT = 1800

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------- the runtime


def generate(model: str, prompt: str) -> dict:
    """One /api/generate call with deliberation off. Never raises for a model
    error; returns a dict carrying `error` instead."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.read()[:400].decode('utf-8', 'replace')}",
                "wall_s": time.time() - t0}
    except Exception as exc:  # noqa: BLE001 - a transport failure is a run fact
        return {"error": f"{type(exc).__name__}: {exc}", "wall_s": time.time() - t0}

    gen_ns = data.get("eval_duration") or 0
    pe_ns = data.get("prompt_eval_duration") or 0
    return {
        "response": data.get("response", ""),
        "thinking": data.get("thinking") or "",
        "done_reason": data.get("done_reason"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "gen_tok_s": (data.get("eval_count") or 0) / (gen_ns / 1e9) if gen_ns else None,
        "prompt_tok_s": (data.get("prompt_eval_count") or 0) / (pe_ns / 1e9) if pe_ns else None,
        "wall_s": time.time() - t0,
        "num_ctx": NUM_CTX,
        "num_predict": NUM_PREDICT,
    }


# --------------------------------------------------------------- extraction


def extract_block(text: str, want: str | None = None) -> str | None:
    """The last fenced block, preferring one whose language tag matches `want`.
    Falls back to the whole text when the model emitted no fence at all."""
    blocks = _FENCE.findall(text)
    if blocks:
        if want:
            tagged = [b for lang, b in blocks if lang.lower() in (want, "")]
            if tagged:
                return tagged[-1]
        return blocks[-1][1]
    stripped = text.strip()
    return stripped or None


_FINAL = re.compile(r"^\s*(?:\*\*)?FINAL(?:\*\*)?\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)


def extract_final(text: str) -> str | None:
    matches = _FINAL.findall(text)
    return matches[-1] if matches else None


def normalise(answer: str) -> str:
    s = answer.strip()
    for ch in ("`", "*", "_"):
        s = s.strip(ch)
    s = s.strip()
    s = s.rstrip(".")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(",", ", ").replace(" ,", ",")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def exact_matches(expected: str, got: str) -> bool:
    a, b = normalise(expected), normalise(got)
    if a == b:
        return True
    if a.lower() == b.lower():
        return True
    try:
        return float(re.sub(r"[,\s]", "", a)) == float(re.sub(r"[,\s]", "", b))
    except ValueError:
        return False


# ------------------------------------------------------------------ scoring


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


def score_exact_task(task: dict, text: str) -> tuple[float, list]:
    got = extract_final(text)
    if got is None:
        return 0.0, [["final line", False, "no FINAL: line in the response"]]
    ok = exact_matches(task["expected"], got)
    return (1.0 if ok else 0.0), [["final line", ok, f"got {got!r} want {task['expected']!r}"]]


def score(task: dict, text: str) -> tuple[float, list]:
    if task["kind"] == "code":
        return score_code_task(task, text)
    return score_exact_task(task, text)


# ------------------------------------------------------- one sample, end to end


def sample(model: str, task: dict) -> dict:
    """One model call plus its scoring. `score` is None when the sample produced
    no result, which is never the same thing as a zero."""
    r = generate(model, task["prompt"])
    rec = {
        "model": model,
        "task": task["id"],
        "group": task["group"],
        "kind": task["kind"],
        **{k: v for k, v in r.items() if k not in ("response", "thinking")},
    }
    rec["thinking_chars"] = len(r.get("thinking", "") or "")

    if "error" in r:
        rec["score"] = None
        rec["no_result"] = "transport: " + r["error"]
        return rec

    text = r["response"] or ""
    rec["response_chars"] = len(text)

    if task["kind"] == "code":
        want = "json" if task.get("kind_hint") == "json" else "python"
        extracted = extract_block(text, want=want)
    else:
        extracted = extract_final(text)

    # Section 5: truncation is not a wrong answer.
    if r.get("done_reason") == "length" and not extracted:
        rec["score"] = None
        rec["no_result"] = "truncated at num_predict with no answer"
        return rec
    if not text.strip():
        rec["score"] = None
        rec["no_result"] = "empty response"
        return rec

    s, detail = score(task, text)
    rec["score"] = s
    rec["detail"] = detail
    rec["truncated_but_scored"] = r.get("done_reason") == "length"
    # Kept so that a saturated task can be diagnosed from what the model wrote
    # rather than from its score, which was the gap when the first set saturated.
    rec["response"] = text
    return rec
