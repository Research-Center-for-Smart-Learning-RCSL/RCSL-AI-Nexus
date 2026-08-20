from harness_parts.client import generate
from harness_parts.extraction import extract_block, extract_final
from harness_parts.scoring import score


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
