import json
import os
import time
import urllib.error
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
NUM_CTX = 16384
NUM_PREDICT = 4096
HTTP_TIMEOUT = 1800

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
