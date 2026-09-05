"""Multi-turn scoring, for the properties a single prompt cannot reach.

Everything else in this harness asks one question and scores one answer. Four of
the five things an education agent has to be trusted with only exist across
turns: whether it still obeys its system prompt at turn eight, whether a student
can talk it out of that prompt, whether it still knows which step of the lesson
it is on after a digression, and whether it pulls a wandering student back
without being asked to. A single-turn task cannot ask any of them.

**The model's own replies are fed back as history.** That is what makes this
compound: a model that leaks the answer at turn three is answering turn four with
the leak in its context, and a model that loses the lesson step does not get it
handed back. The existing set has no task with that property, and its absence is
part of why eleven of eighteen tasks carried no signal -- a single-shot task has
one chance to go wrong and no way to go wrong twice.

**Scoring stays programmatic.** The rule this harness runs on is that nothing is
judged by reading it, and pedagogy is exactly the material where that rule is
tempting to break. It is not broken here: the system prompt under test requires a
structured trailer on every reply (`NEXT: <step>`), which is how real agent
platforms drive orchestration anyway, so "does it still know which step it is on"
becomes a string comparison rather than a judgement. Checks are Python
expressions over the reply text, the same shape the code tasks already use.

What this cannot measure is whether the tutoring is any *good* -- whether the
Socratic question asked was the right one for this student. That is the same
boundary section 6 draws for the code tasks, and it is drawn here for the same
reason: a scorer that cannot be wrong about its own verdict is worth more than a
richer one that can.
"""

from __future__ import annotations

import re


def _predicate_env(reply: str, turn_index: int, history: list[dict]) -> dict:
    """The names a check expression may use.

    Deliberately small. A check that needs more than these is usually a check
    that has started judging the prose rather than testing a property of it.
    """
    stripped = reply.strip()
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    next_line = None
    for ln in reversed(lines):
        m = re.match(r"^\s*NEXT\s*:\s*(.+?)\s*$", ln, re.IGNORECASE)
        if m:
            next_line = m.group(1).strip()
            break

    def contains_any(needles) -> bool:
        low = stripped.lower()
        return any(str(n).lower() in low for n in needles)

    def contains_number(value) -> bool:
        """Whether a specific numeric value appears as a standalone number.

        Substring matching is wrong here and quietly so: the answer 42 is inside
        "426", and a tutor that says "step 42 of the worksheet" has not leaked
        the answer 42. The boundary is what makes a leak check mean leak.
        """
        pattern = r"(?<![\d.,])" + re.escape(str(value)) + r"(?![\d.,]*\d)"
        return re.search(pattern, stripped) is not None

    return {
        "reply": stripped,
        "lower": stripped.lower(),
        "lines": lines,
        "next_step": next_line,
        "turn": turn_index,
        "history": history,
        "re": re,
        "contains_any": contains_any,
        "contains_number": contains_number,
        "question_marks": stripped.count("?"),
    }


def score_dialogue_task(task: dict, replies: list[str]) -> tuple[float, list]:
    """Score a completed conversation against its per-turn checks.

    `replies[i]` is what the model said to `task["turns"][i]["student"]`. A
    conversation that ended early -- because a turn produced no text at all --
    scores its missing turns as failures rather than shortening the denominator,
    since a tutor that stops replying has failed the turn in the way that
    matters to a student.
    """
    detail: list = []
    history: list[dict] = []
    for i, turn in enumerate(task["turns"]):
        reply = replies[i] if i < len(replies) else ""
        env = _predicate_env(reply, i, list(history))
        for name, expr in turn.get("checks", []):
            label = f"t{i}:{name}"
            if not reply.strip():
                detail.append([label, False, "no reply for this turn"])
                continue
            try:
                ok = bool(eval(expr, {"__builtins__": __builtins__}, env))  # noqa: S307
                detail.append([label, ok, "" if ok else f"failed: {expr}"])
            except Exception as exc:  # noqa: BLE001 - a broken check is a run fact
                detail.append([label, False, f"{type(exc).__name__}: {exc}"])
        history.append({"student": turn["student"], "reply": reply})

    passed = sum(1 for _, ok, _ in detail if ok)
    return (passed / len(detail) if detail else 0.0), detail


def run_dialogue(model: str, task: dict, chat_fn) -> tuple[list[str], list[dict]]:
    """Drive the scripted conversation, returning the model's replies and the raw calls.

    `chat_fn(model, messages)` is injected rather than imported so this module
    stays testable without a runtime, which is the same reason `validate.py` can
    check a dialogue task's reference without Ollama running.
    """
    messages = [{"role": "system", "content": task["system"]}]
    replies: list[str] = []
    calls: list[dict] = []
    for turn in task["turns"]:
        messages.append({"role": "user", "content": turn["student"]})
        r = chat_fn(model, messages)
        calls.append(r)
        if "error" in r:
            break
        text = r.get("response", "") or ""
        replies.append(text)
        messages.append({"role": "assistant", "content": text})
    return replies, calls
