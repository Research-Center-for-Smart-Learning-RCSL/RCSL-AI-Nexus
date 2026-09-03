from harness_parts.client import chat, generate
from harness_parts.dialogue import run_dialogue
from harness_parts.extraction import extract_block, extract_final
from harness_parts.scoring import score


def sample_dialogue(model: str, task: dict) -> dict:
    """One scripted conversation plus its scoring.

    The per-turn figures are summed rather than averaged where they are counts
    and averaged where they are rates, because a conversation is one sample of a
    task and has to compare against a single-turn sample of another one. The
    depth recorded is the *last* turn's, which is the one that actually says how
    much context the model was holding when it answered -- an average over a
    growing conversation describes no moment in it.
    """
    replies, calls = run_dialogue(model, task, chat)
    rec = {
        "model": model,
        "task": task["id"],
        "group": task["group"],
        "kind": task["kind"],
        "turns_run": len(replies),
        "turns_scripted": len(task["turns"]),
        "wall_s": sum(c.get("wall_s") or 0 for c in calls),
        "eval_count": sum(c.get("eval_count") or 0 for c in calls),
        "prompt_eval_count": (calls[-1].get("prompt_eval_count") if calls else None),
        "num_ctx": next((c["num_ctx"] for c in calls if "num_ctx" in c), None),
        "num_predict": next((c["num_predict"] for c in calls if "num_predict" in c), None),
        "thinking_chars": sum(len(c.get("thinking") or "") for c in calls),
    }
    rates = [c["gen_tok_s"] for c in calls if c.get("gen_tok_s")]
    rec["gen_tok_s"] = sum(rates) / len(rates) if rates else None

    failed = [c for c in calls if "error" in c]
    if failed:
        rec["score"] = None
        rec["outcome"] = "transport_error"
        rec["no_result"] = f"transport on turn {len(calls) - 1}: " + failed[0]["error"]
        return rec

    # A conversation that ran to the end is scored even if a turn was truncated:
    # unlike a single-turn task there is no one answer to have been cut off, and
    # a reply that was cut off mid-sentence is a reply the student received. What
    # is recorded is that it happened, so the figure can be read with that in mind.
    rec["truncated_turns"] = sum(1 for c in calls if c.get("done_reason") == "length")
    s, detail = score(task, replies)
    rec["score"] = s
    rec["outcome"] = "scored"
    rec["detail"] = detail
    rec["response"] = "\n\n<<<TURN>>>\n\n".join(replies)
    rec["response_chars"] = len(rec["response"])
    return rec


def sample(model: str, task: dict) -> dict:
    """One model call plus its scoring. `score` is None when the sample produced
    no result, which is never the same thing as a zero."""
    if task["kind"] == "dialogue":
        return sample_dialogue(model, task)
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
        rec["outcome"] = "transport_error"
        rec["no_result"] = "transport: " + r["error"]
        return rec

    text = r["response"] or ""
    rec["response_chars"] = len(text)

    if task["kind"] == "code":
        want = "json" if task.get("kind_hint") == "json" else "python"
        extracted = extract_block(text, want=want)
    else:
        extracted = extract_final(text)

    # Section 5: truncation is not a wrong answer -- and 2026-09-02 measured the
    # case where that rule cuts the other way. With deliberation off and
    # `thinking_chars` zero, a model that runs out the budget on prose without
    # reaching an answer is failing to follow the output instruction, not having
    # its reasoning cut off, and excluding the sample credits it for a task it
    # could not finish. Scoring it 0 instead credits the harness for a
    # measurement it did not make when the budget genuinely was the constraint.
    #
    # **So this is the third outcome both readings were asking for**, rather than
    # a choice between them: the sample is still excluded from the mean, which
    # keeps the recorded rule intact and every earlier phase comparable, and it
    # is now labelled distinctly enough that `analyse.py` can report the
    # score-them-0 reading beside the score-them-nothing one without anybody
    # re-deriving it by hand. The 2026-09-02 entry had to publish both by hand
    # for exactly this reason.
    if r.get("done_reason") == "length" and not extracted:
        rec["score"] = None
        rec["outcome"] = "truncated_no_answer"
        rec["no_result"] = "truncated at num_predict with no answer"
        # Kept for the same reason the scored path keeps it, and with more force:
        # this is the sample where the question is *what the budget went on*, and
        # answering it from `thinking_chars` alone -- which is all 2026-09-02 had
        # -- cannot distinguish a model working steadily through a trace too long
        # to fit from a model padding. The first version of this branch returned
        # before storing the text, so the one sample that most needed reading was
        # the one that could not be read.
        rec["response"] = text
        return rec
    if not text.strip():
        rec["score"] = None
        rec["outcome"] = "empty"
        rec["no_result"] = "empty response"
        return rec

    s, detail = score(task, text)
    rec["score"] = s
    rec["outcome"] = "scored"
    rec["detail"] = detail
    rec["truncated_but_scored"] = r.get("done_reason") == "length"
    # Kept so that a saturated task can be diagnosed from what the model wrote
    # rather than from its score, which was the gap when the first set saturated.
    rec["response"] = text
    return rec
