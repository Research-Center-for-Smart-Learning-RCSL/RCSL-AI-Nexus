import re

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)

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
