from harness_parts.code_scoring import score_code_task
from harness_parts.dialogue import score_dialogue_task
from harness_parts.extraction import exact_matches, extract_final


def score_exact_task(task: dict, text: str) -> tuple[float, list]:
    got = extract_final(text)
    if got is None:
        return 0.0, [["final line", False, "no FINAL: line in the response"]]
    ok = exact_matches(task["expected"], got)
    return (1.0 if ok else 0.0), [["final line", ok, f"got {got!r} want {task['expected']!r}"]]


def score(task: dict, text) -> tuple[float, list]:
    if task["kind"] == "code":
        return score_code_task(task, text)
    # A dialogue's "answer" is the list of replies the conversation produced, so
    # its reference and wrong answers are lists too. Keeping the same `score`
    # entry point is what lets `validate.py` check both directions for these
    # tasks without knowing anything about turns.
    if task["kind"] == "dialogue":
        return score_dialogue_task(task, text)
    return score_exact_task(task, text)
