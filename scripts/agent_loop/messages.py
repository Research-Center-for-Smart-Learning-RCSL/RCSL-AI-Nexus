def assistant_turn(message):
    """Replay the assistant's own turn, calls included, as an agent client must."""
    turn = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        turn["tool_calls"] = message["tool_calls"]
    return turn


def tool_result(call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def uses(text, digits):
    """Whether an answer actually carries a number, however it renders it.

    Asserting on free text is phrase-sensitive, and the sensitivity is real
    rather than theoretical: one run of rung 8 answered correctly and was
    marked FAIL because it wrote the figure another way. Separators are
    stripped and the common "2.6 million" form is accepted, which keeps the
    assertion about *using the result* rather than about matching one
    rendering. It is deliberately not loosened further — the digits still have
    to appear, or the rung stops testing anything.
    """
    flat = text.replace(",", "").replace(" ", "").replace("\u00a0", "").lower()
    if digits in flat:
        return True
    millions = int(digits) / 1_000_000
    return any(f"{millions:.{p}f}".rstrip("0").rstrip(".") + "million" in flat for p in (0, 1, 2))


def answer_of(final):
    """The assistant's closing answer, or "" if it never produced one.

    Read from the turn that ended the loop rather than from `messages[-1]`,
    which is what the first version did and which is wrong in the one case that
    matters. When a rung exhausts its turn budget with a call still pending, the
    last element is a *tool result* — and the injected results here contain the
    very substrings the assertions look for ("13,960,000", "2,600,000"), so a
    model that never stopped calling was reported as having used the answer.
    A rung that exists to prove the result was consumed must not be satisfiable
    by the result being present in the input.
    """
    return (final.get("content") or "") if final else ""


# --- the rungs -----------------------------------------------------------
