import json
import os
import time
import urllib.error
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# Overridable per run, and defaulted to what every phase through `qwen38` was
# measured at, so raising the budget for a new phase cannot silently restate the
# conditions of an old one. Every sample records both values, so a row says what
# it was generated under rather than inheriting whatever the constant says today.
#
# The reason there is a lever at all: with deliberation off, a model's working
# comes out in `response` rather than in `thinking`, so a task that needs more
# steps needs more output budget for the same amount of answer. On 2026-09-02
# three builds spent the whole 4096 on prose and reached no answer at all, and a
# harder task set makes that failure more likely, not less. A budget that is
# several times the expected answer is section 5's own requirement; this is how
# a phase meets it without moving the floor under the phases already recorded.
NUM_CTX = int(os.environ.get("EVAL_NUM_CTX", "16384"))
NUM_PREDICT = int(os.environ.get("EVAL_NUM_PREDICT", "4096"))
HTTP_TIMEOUT = 1800

def chat(model: str, messages: list[dict]) -> dict:
    """One /api/chat call, for the multi-turn tasks.

    Separate from `generate` rather than folded into it because the two carry
    different conditions and a row has to say which it was measured under: this
    one sends a system role, which `/api/generate` has no place for, and the
    system prompt is the thing under test in every task that uses this.

    Deliberation is off here for the same reason it is off there -- it matches
    the `assist` policy this deployment actually serves, and a model whose
    reasoning is hidden from the transcript is not the one a student talks to.
    """
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"}
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

    msg = data.get("message") or {}
    gen_ns = data.get("eval_duration") or 0
    pe_ns = data.get("prompt_eval_duration") or 0
    return {
        "response": msg.get("content", ""),
        "thinking": msg.get("thinking") or "",
        "done_reason": data.get("done_reason"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "gen_tok_s": (data.get("eval_count") or 0) / (gen_ns / 1e9) if gen_ns else None,
        "prompt_tok_s": (data.get("prompt_eval_count") or 0) / (pe_ns / 1e9) if pe_ns else None,
        "wall_s": time.time() - t0,
        "num_ctx": NUM_CTX,
        "num_predict": NUM_PREDICT,
    }


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
