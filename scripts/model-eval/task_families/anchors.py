from task_registry import CODE_SUFFIX, EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# Anchors, carried over from the first set.
#
# RECONSTRUCTED, not carried over verbatim: the first set's harness was never
# committed, so the original wording of these two is gone. They are rebuilt from
# the description in PROGRESS.md 2026-08-14 and are therefore NOT a valid bridge
# between the two sets. Recorded here rather than quietly.
# --------------------------------------------------------------------------

task(
    id="ini_parse",
    group="anchor",
    kind="code",
    prompt=(
        "Write a Python function `parse_ini(text)` returning a dict of section name -> dict of "
        "key -> value, both strings.\n\n"
        "Rules:\n\n"
        "- A section header is a line whose stripped form is `[name]`. Keys before any header "
        "belong to the section `DEFAULT`.\n"
        "- A key and its value are separated by the first `=` **or** the first `:`, whichever "
        "appears earlier in the line. A separator inside the value is part of the value.\n"
        "- Keys and values are stripped of surrounding whitespace. Keys are lowercased; values "
        "are not.\n"
        "- A line whose first non-whitespace character is `;` or `#` is a comment and is ignored. "
        "A `;` or `#` appearing later in a line is part of the value.\n"
        "- A line that is more indented than the key line before it and contains no separator is "
        "a continuation: its stripped text is appended to the previous value with a single "
        "space between.\n"
        "- A key repeated in the same section takes its last value.\n"
        "- Blank lines are ignored. A section that appears twice is one section.\n"
        "- A section with no keys still appears, with an empty dict."
        + CODE_SUFFIX
    ),
    checks=[
        ("basic sections and keys", """
_r = parse_ini("[a]\\nx = 1\\ny = 2\\n[b]\\nz = 3\\n")
assert _r == {"a": {"x": "1", "y": "2"}, "b": {"z": "3"}}, _r
""", 10),
        ("keys before any header go to DEFAULT", """
_r = parse_ini("top = 1\\n[a]\\nx = 2\\n")
assert _r == {"DEFAULT": {"top": "1"}, "a": {"x": "2"}}, _r
""", 10),
        ("colon separator and earliest-separator rule", """
_r = parse_ini("[a]\\nurl: http://h/p?q=1\\nk = v:w\\n")
assert _r["a"]["url"] == "http://h/p?q=1", _r
assert _r["a"]["k"] == "v:w", _r
""", 10),
        ("comments whole-line only", """
_r = parse_ini("[a]\\n; skip\\n  # skip too\\nx = 1 ; kept\\ny = a#b\\n")
assert _r == {"a": {"x": "1 ; kept", "y": "a#b"}}, _r
""", 10),
        ("continuation lines", """
_r = parse_ini("[a]\\nmsg = hello\\n    world\\n    again\\nnext = 1\\n")
assert _r["a"]["msg"] == "hello world again", _r
assert _r["a"]["next"] == "1", _r
""", 10),
        ("last value wins", """
_r = parse_ini("[a]\\nx = 1\\nx = 2\\n")
assert _r == {"a": {"x": "2"}}, _r
""", 10),
        ("keys lowercased, values not", """
_r = parse_ini("[a]\\nKeyName = ValueCase\\n")
assert _r == {"a": {"keyname": "ValueCase"}}, _r
""", 10),
        ("repeated section merges, empty section kept", """
_r = parse_ini("[a]\\nx = 1\\n[b]\\n[a]\\ny = 2\\n")
assert _r == {"a": {"x": "1", "y": "2"}, "b": {}}, _r
""", 10),
    ],
    reference='''
def parse_ini(text):
    out = {}
    section = "DEFAULT"
    cur_key = None
    cur_indent = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped[0] in ";#":
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            out.setdefault(section, {})
            cur_key = None
            continue
        indent = len(raw) - len(raw.lstrip())
        ie = stripped.find("=")
        ic = stripped.find(":")
        cands = [i for i in (ie, ic) if i != -1]
        sep = min(cands) if cands else -1
        if sep == -1:
            if cur_key is not None and indent > cur_indent:
                out.setdefault(section, {})
                out[section][cur_key] = (out[section][cur_key] + " " + stripped).strip()
            continue
        key = stripped[:sep].strip().lower()
        value = stripped[sep + 1:].strip()
        out.setdefault(section, {})
        out[section][key] = value
        cur_key = key
        cur_indent = indent
    out.setdefault(section, {})
    return out
''',
    wrong='''
def parse_ini(text):
    out = {}
    section = "DEFAULT"
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped[0] in ";#":
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            out.setdefault(section, {})
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out.setdefault(section, {})[key.strip().lower()] = value.split(";")[0].strip()
    return out
''',
)

task(
    id="logic_order",
    group="anchor",
    kind="exact",
    prompt=(
        "Five services — Atlas, Beacon, Cedar, Dial and Ember — are started one after another, "
        "each at a distinct position from 1st to 5th.\n\n"
        "1. Cedar starts at some point before Ember, but not immediately before.\n"
        "2. Exactly two services start between Atlas and Dial, in some order.\n"
        "3. Beacon does not start 1st and does not start 5th.\n"
        "4. Beacon starts immediately after Dial.\n"
        "5. Atlas does not start 1st.\n"
        "6. Ember does not start 5th.\n\n"
        "Exactly one order satisfies all six. Give it, 1st to 5th, as five names separated by a "
        "comma and a space." + EXACT_SUFFIX
    ),
    expected="Cedar, Dial, Beacon, Ember, Atlas",
    reference="FINAL: Cedar, Dial, Beacon, Ember, Atlas",
    wrong="FINAL: Dial, Beacon, Cedar, Atlas, Ember",
)
