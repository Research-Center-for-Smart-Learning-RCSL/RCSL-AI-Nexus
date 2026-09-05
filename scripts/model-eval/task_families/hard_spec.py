from task_registry import CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# M - dense, interacting specification rules
#
# The set has saturated twice: every mechanism except the INI parser scored 1.00
# for every model in every family. The one thing that separated them was a pile
# of small boundary rules that interact, where holding rule 9 in mind while
# implementing rule 4 is the actual work. These two tasks are that mechanism,
# turned up: many independently-checkable rules, one of which quietly reorders
# the obvious implementation.
# --------------------------------------------------------------------------


# Meant to separate models that implement each rule locally from models that
# notice the application-order rule governs every other rule in the list.
task(
    id="config_merge",
    group="M",
    kind="code",
    prompt=(
        "Write a Python function `merge(base, overlay)` that returns a new dict combining a "
        "configuration dict `base` with an overlay dict `overlay`. Neither argument may be "
        "mutated.\n\n"
        "The result starts as a deep copy of `base`, and the overlay's keys are then applied to "
        "that result one at a time. Each rule below tests and modifies the result as it stands at "
        "the moment that key is applied.\n\n"
        "Rules:\n\n"
        "- A key present in the result and not in the overlay is left unchanged. An empty overlay "
        "returns a copy of `base`.\n"
        "- A plain key whose value in the result and whose value in the overlay are both dicts is "
        "merged recursively, the overlay's nested dict being an overlay in its own right and "
        "following all of these rules. Otherwise the overlay's value replaces the result's value.\n"
        "- A list value under a plain key replaces the result's value; it is not concatenated.\n"
        "- A key written `key+` appends its value, which is a list, to the list under `key` in the "
        "result. A key written `+key` prepends it. If `key` is not in the result, both behave as "
        "though it held an empty list.\n"
        "- A key written `!key` removes `key` from the result; the value under `!key` is ignored. "
        "Removing a key that is not in the result is a no-op.\n"
        "- A key written `~key` sets `key` to its value only if `key` is not in the result, and "
        "does nothing otherwise. The value is used as it is, with no recursive merge.\n"
        "- `None` is an ordinary value like any other.\n"
        "- Within one overlay dict, keys are applied in sorted order of the key name with its "
        "sigil removed, and two keys that reduce to the same name are applied in the order "
        "remove, set-if-absent, prepend, append, plain set.\n"
        "- `!`, `~` and `+` are sigils only as the first character of a key, and `+` is also a "
        "sigil as the last character. A key holding one of those characters anywhere else is an "
        "ordinary key, sigil-free.\n"
        "- A plain key raises `TypeError` if the key is in the result and exactly one of the two "
        "values is a dict.\n"
        "- `key+` and `+key` raise `TypeError` if the overlay's value is not a list, and raise "
        "`TypeError` if `key` is in the result holding something that is not a list.\n"
        "- These rules apply at every depth of nesting."
        + CODE_SUFFIX
    ),
    checks=[
        ("recursive dict merge, scalar replace", """
_b = {"a": {"x": 1, "y": 2}, "n": 5}
_o = {"a": {"y": 9, "z": 3}, "n": 6}
assert merge(_b, _o) == {"a": {"x": 1, "y": 9, "z": 3}, "n": 6}, merge(_b, _o)
""", 10),
        ("keys only in base survive, empty overlay copies", """
_b = {"a": 1, "b": {"c": 2}}
assert merge(_b, {}) == _b
assert merge(_b, {}) is not _b
assert merge(_b, {"a": 2}) == {"a": 2, "b": {"c": 2}}
""", 10),
        ("plain list key replaces", """
assert merge({"l": [1, 2]}, {"l": [3]}) == {"l": [3]}
assert merge({"l": [1, 2]}, {"l": []}) == {"l": []}
""", 10),
        ("append with key+", """
assert merge({"l": [1, 2]}, {"l+": [3, 4]}) == {"l": [1, 2, 3, 4]}
""", 10),
        ("prepend with +key", """
assert merge({"l": [1, 2]}, {"+l": [0]}) == {"l": [0, 1, 2]}
""", 10),
        ("append and prepend when base lacks the key", """
assert merge({}, {"l+": [1]}) == {"l": [1]}
assert merge({"k": 1}, {"+l": [2, 3]}) == {"k": 1, "l": [2, 3]}
""", 10),
        ("delete with !key, absent delete is a no-op", """
assert merge({"a": 1, "b": 2}, {"!a": None}) == {"b": 2}
assert merge({"a": 1}, {"!zz": 12345}) == {"a": 1}
assert merge({}, {"!zz": None}) == {}
""", 10),
        ("set-if-absent with ~key", """
assert merge({"a": 1}, {"~a": 9}) == {"a": 1}
assert merge({"a": 1}, {"~b": 9}) == {"a": 1, "b": 9}
assert merge({"a": {"x": 1}}, {"~b": {"y": 2}}) == {"a": {"x": 1}, "b": {"y": 2}}
""", 10),
        ("None is an ordinary value", """
_r = merge({"a": 1, "b": 2}, {"a": None})
assert _r == {"a": None, "b": 2}, _r
assert "a" in _r
_r2 = merge({}, {"~a": None})
assert _r2 == {"a": None}, _r2
""", 10),
        ("dict against non-dict raises TypeError", """
try:
    merge({"a": {"x": 1}}, {"a": 5})
    raise AssertionError("no TypeError for dict overwritten by scalar")
except TypeError:
    pass
try:
    merge({"a": 5}, {"a": {"x": 1}})
    raise AssertionError("no TypeError for scalar overwritten by dict")
except TypeError:
    pass
""", 10),
        ("append onto a non-list, or of a non-list, raises TypeError", """
try:
    merge({"a": 5}, {"a+": [1]})
    raise AssertionError("no TypeError appending to a non-list base")
except TypeError:
    pass
try:
    merge({"a": [1]}, {"a+": 2})
    raise AssertionError("no TypeError appending a non-list value")
except TypeError:
    pass
try:
    merge({"a": [1]}, {"+a": "x"})
    raise AssertionError("no TypeError prepending a non-list value")
except TypeError:
    pass
""", 10),
        ("delete and append on one name", """
_r = merge({"l": [1, 2]}, {"l+": [3], "!l": None})
assert _r == {"l": [3]}, _r
""", 10),
        ("set-if-absent after a delete on one name", """
_r = merge({"a": 1}, {"~a": 9, "!a": None})
assert _r == {"a": 9}, _r
""", 10),
        ("prepend, append and plain set on one name", """
_r = merge({"l": [0]}, {"l": [9], "+l": [1], "l+": [2]})
assert _r == {"l": [9]}, _r
_r2 = merge({"l": [0]}, {"+l": [1], "l+": [2]})
assert _r2 == {"l": [1, 0, 2]}, _r2
""", 10),
        ("sigil characters elsewhere are ordinary", """
_b = {"a+b": 1, "b!c": 2, "x~y": 3}
_o = {"a+b": 9, "b!c": 8, "x~y": 7}
assert merge(_b, _o) == {"a+b": 9, "b!c": 8, "x~y": 7}
assert merge({}, {"p!q": 1}) == {"p!q": 1}
""", 10),
        ("sigils three levels deep", """
_b = {"a": {"b": {"c": [1], "d": 2, "e": 3}}}
_o = {"a": {"b": {"c+": [4], "!d": None, "~f": 6, "~e": 99}}}
_r = merge(_b, _o)
assert _r == {"a": {"b": {"c": [1, 4], "e": 3, "f": 6}}}, _r
""", 10),
        ("neither argument is mutated", """
import copy as _copy
_b = {"a": {"x": [1, 2]}, "b": 1, "c": [3]}
_o = {"a": {"x+": [3], "~y": 2}, "!b": None, "c": [9]}
_bc = _copy.deepcopy(_b)
_oc = _copy.deepcopy(_o)
_r = merge(_b, _o)
assert _b == _bc, _b
assert _o == _oc, _o
_r["a"]["x"].append(99)
assert _b == _bc, _b
""", 10),
        ("several names at once", """
_b = {"z": 1, "a": [1], "m": {"k": 1}}
_o = {"z": 2, "a+": [2], "m": {"k": 2, "~j": 3}, "~q": 4}
_r = merge(_b, _o)
assert _r == {"z": 2, "a": [1, 2], "m": {"k": 2, "j": 3}, "q": 4}, _r
""", 10),
    ],
    reference='''
import copy

_RANK = {"delete": 0, "absent": 1, "prepend": 2, "append": 3, "set": 4}


def _classify(key):
    if key.startswith("!"):
        return "delete", key[1:]
    if key.startswith("~"):
        return "absent", key[1:]
    if key.startswith("+"):
        return "prepend", key[1:]
    if key.endswith("+"):
        return "append", key[:-1]
    return "set", key


def merge(base, overlay):
    result = copy.deepcopy(base)
    plan = []
    for key, value in overlay.items():
        op, name = _classify(key)
        plan.append((name, _RANK[op], op, value))
    # The spec's order, not the dict's: same-name operations have to run
    # remove-first so that a later append sees the removal.
    plan.sort(key=lambda item: (item[0], item[1]))
    for name, _rank, op, value in plan:
        if op == "delete":
            result.pop(name, None)
        elif op == "absent":
            if name not in result:
                result[name] = copy.deepcopy(value)
        elif op in ("prepend", "append"):
            if not isinstance(value, list):
                raise TypeError("%s expects a list value" % op)
            current = result.get(name, [])
            if not isinstance(current, list):
                raise TypeError("%s onto a non-list" % op)
            add = copy.deepcopy(value)
            result[name] = add + current if op == "prepend" else current + add
        else:
            if name in result and isinstance(result[name], dict) != isinstance(value, dict):
                raise TypeError("dict and non-dict conflict at %r" % name)
            if name in result and isinstance(value, dict):
                result[name] = merge(result[name], value)
            else:
                result[name] = copy.deepcopy(value)
    return result
''',
    # Every rule right except the two that need a second pass: overlay keys go in
    # insertion order, and None reads as a deletion.
    wrong='''
import copy


def _classify(key):
    if key.startswith("!"):
        return "delete", key[1:]
    if key.startswith("~"):
        return "absent", key[1:]
    if key.startswith("+"):
        return "prepend", key[1:]
    if key.endswith("+"):
        return "append", key[:-1]
    return "set", key


def merge(base, overlay):
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        op, name = _classify(key)
        if op == "delete":
            result.pop(name, None)
        elif op == "absent":
            if name not in result:
                result[name] = copy.deepcopy(value)
        elif op in ("prepend", "append"):
            if not isinstance(value, list):
                raise TypeError("expects a list")
            current = result.get(name, [])
            if not isinstance(current, list):
                raise TypeError("onto a non-list")
            add = copy.deepcopy(value)
            result[name] = add + current if op == "prepend" else current + add
        elif value is None:
            result.pop(name, None)
        else:
            if name in result and isinstance(result[name], dict) != isinstance(value, dict):
                raise TypeError("conflict")
            if name in result and isinstance(value, dict):
                result[name] = merge(result[name], value)
            else:
                result[name] = copy.deepcopy(value)
    return result
''',
)


# Meant to separate models that get the parser's tokenisation right from models
# that also keep the fraction rule and the canonical-render rule straight.
task(
    id="duration_grammar",
    group="M",
    kind="code",
    prompt=(
        "Write two Python functions. `parse(s)` takes a duration string and returns an integer "
        "number of milliseconds. `render(ms)` takes an integer number of milliseconds and returns "
        "the canonical string for it.\n\n"
        "Rules:\n\n"
        "- The units are `w` (604800000 ms), `d` (86400000 ms), `h` (3600000 ms), `m` (60000 ms), "
        "`s` (1000 ms) and `ms` (1 ms). A day is exactly 24 hours and a week exactly 7 days.\n"
        "- A duration is a run of terms, each a number followed by a unit, with nothing between "
        "them. Whitespace anywhere in the string raises `ValueError`.\n"
        "- The units of the terms run in strictly descending order of size, and no unit appears "
        "twice. A string that breaks either raises `ValueError`.\n"
        "- A number is one or more digits, optionally followed by `.` and one or more digits. "
        "Anything else in the string, including an unknown unit or a unit with no number, raises "
        "`ValueError`.\n"
        "- A string of digits with no unit at all is that many seconds.\n"
        "- A leading `-` negates the whole duration. A `-` anywhere else raises `ValueError`.\n"
        "- Only the smallest unit present in the string may carry a fractional part; a fractional "
        "part on any other term raises `ValueError`.\n"
        "- A fractional number of milliseconds is truncated toward zero.\n"
        "- The empty string raises `ValueError`. The string `0` is valid and is zero.\n"
        "- `render` writes the largest units first, omits every term whose coefficient is zero, "
        "and never writes a fractional part.\n"
        "- `render` returns `0s` for zero, and prefixes a `-` for a negative duration.\n"
        "- `parse(render(x)) == x` holds for every integer `x`."
        + CODE_SUFFIX
    ),
    checks=[
        ("each unit alone", """
assert parse("1w") == 604800000
assert parse("1d") == 86400000
assert parse("1h") == 3600000
assert parse("1m") == 60000
assert parse("1s") == 1000
assert parse("1ms") == 1
""", 10),
        ("m and ms are distinct", """
assert parse("5m") == 300000
assert parse("5ms") == 5
assert parse("2m3s4ms") == 123004
assert parse("1m1ms") == 60001
""", 10),
        ("multi-term durations", """
assert parse("1h30m") == 5400000
assert parse("1w2d3h4m5s6ms") == 604800000 + 172800000 + 10800000 + 240000 + 5000 + 6
assert parse("90m") == 5400000
""", 10),
        ("a bare number is seconds", """
assert parse("90") == 90000
assert parse("0") == 0
assert parse("-45") == -45000
""", 10),
        ("the empty string is an error", """
try:
    parse("")
    raise AssertionError("empty string accepted")
except ValueError:
    pass
""", 10),
        ("whitespace is an error", """
for _s in (" 1h", "1h ", "1h 30m", "1 h", "\\t1s"):
    try:
        parse(_s)
        raise AssertionError("accepted %r" % _s)
    except ValueError:
        pass
""", 10),
        ("units out of order are an error", """
for _s in ("30m1h", "1s1h", "5ms5s", "1d1w"):
    try:
        parse(_s)
        raise AssertionError("accepted %r" % _s)
    except ValueError:
        pass
""", 10),
        ("a repeated unit is an error", """
for _s in ("1h1h", "5m5m", "1h30m20m", "2ms3ms"):
    try:
        parse(_s)
        raise AssertionError("accepted %r" % _s)
    except ValueError:
        pass
""", 10),
        ("a negative sign leads or is an error", """
assert parse("-1h30m") == -5400000
assert parse("-1ms") == -1
for _s in ("1h-30m", "1-h", "5s-", "--1s"):
    try:
        parse(_s)
        raise AssertionError("accepted %r" % _s)
    except ValueError:
        pass
""", 10),
        ("malformed terms are an error", """
for _s in ("5x", "abc", "h", "1hh", "1.h", "1.5", "1..5s", "s5"):
    try:
        parse(_s)
        raise AssertionError("accepted %r" % _s)
    except ValueError:
        pass
""", 10),
        ("a fraction on the smallest unit present", """
assert parse("1.5s") == 1500
assert parse("1h0.5m") == 3630000
assert parse("1w2d0.25h") == 604800000 + 172800000 + 900000
assert parse("0.5s") == 500
""", 10),
        ("a fraction on any larger term is an error", """
for _s in ("1.5h30m", "1.5w2d", "1.5m30s", "0.5d1h1s"):
    try:
        parse(_s)
        raise AssertionError("accepted %r" % _s)
    except ValueError:
        pass
""", 10),
        ("fractional milliseconds truncate toward zero", """
assert parse("1.9ms") == 1
assert parse("0.5ms") == 0
assert parse("-1.9ms") == -1
assert parse("1s0.999ms") == 1000
assert parse("1.0004s") == 1000
""", 10),
        ("render writes the canonical simple cases", """
assert render(0) == "0s"
assert render(1) == "1ms"
assert render(1000) == "1s"
assert render(60000) == "1m"
assert render(604800000) == "1w"
""", 10),
        ("render omits zero terms", """
assert render(3600001) == "1h1ms"
assert render(604800000 + 5) == "1w5ms"
assert render(86400000 + 60000) == "1d1m"
assert render(5400000) == "1h30m"
""", 10),
        ("render signs negatives", """
assert render(-5400000) == "-1h30m"
assert render(-1) == "-1ms"
assert render(-1000) == "-1s"
""", 10),
        ("round trip over pinned values", """
for _x in (0, 1, -1, 999, 1000, -1000, 59999, 86399999, 604800000, -604800001,
           123456789, -987654321, 1234567890123, 7, -7):
    assert parse(render(_x)) == _x, (_x, render(_x))
""", 15),
        ("parse and render agree on pinned strings", """
assert render(parse("1w2d3h4m5s6ms")) == "1w2d3h4m5s6ms"
assert render(parse("90")) == "1m30s"
assert render(parse("1.5s")) == "1s500ms"
assert render(parse("-1h30m")) == "-1h30m"
assert render(parse("0")) == "0s"
""", 10),
    ],
    reference='''
import re

_UNITS = [("w", 604800000), ("d", 86400000), ("h", 3600000),
          ("m", 60000), ("s", 1000), ("ms", 1)]
_SIZE = dict(_UNITS)
_RANK = {name: i for i, (name, _) in enumerate(_UNITS)}
# ms is listed before m so that the longer unit wins the match.
_TERM = re.compile(r"(\\d+)(?:\\.(\\d+))?(ms|w|d|h|m|s)")


def parse(s):
    if not isinstance(s, str) or s == "":
        raise ValueError("empty duration")
    if any(ch.isspace() for ch in s):
        raise ValueError("whitespace in duration")
    negative = s.startswith("-")
    body = s[1:] if negative else s
    if body == "" or "-" in body:
        raise ValueError("misplaced sign")
    if body.isdigit():
        total = int(body) * 1000
        return -total if negative else total
    terms = []
    pos = 0
    while pos < len(body):
        m = _TERM.match(body, pos)
        if m is None:
            raise ValueError("bad term at %d" % pos)
        terms.append(m.groups())
        pos = m.end()
    if not terms:
        raise ValueError("no terms")
    ranks = [_RANK[t[2]] for t in terms]
    for i in range(len(ranks) - 1):
        if ranks[i] >= ranks[i + 1]:
            raise ValueError("units out of order or repeated")
    smallest = terms[-1][2]
    total = 0
    for whole, frac, unit in terms:
        size = _SIZE[unit]
        if frac is not None and unit != smallest:
            raise ValueError("fraction on a unit that is not the smallest present")
        total += int(whole) * size
        if frac is not None:
            total += int(frac) * size // (10 ** len(frac))
    return -total if negative else total


def render(ms):
    if ms == 0:
        return "0s"
    rest = -ms if ms < 0 else ms
    parts = []
    for name, size in _UNITS:
        count, rest = divmod(rest, size)
        if count:
            parts.append("%d%s" % (count, name))
    return ("-" if ms < 0 else "") + "".join(parts)
''',
    # Parses in the usual way but drops the fraction restriction, and renders
    # every unit whether or not its coefficient is zero.
    wrong='''
import re

_UNITS = [("w", 604800000), ("d", 86400000), ("h", 3600000),
          ("m", 60000), ("s", 1000), ("ms", 1)]
_SIZE = dict(_UNITS)
_RANK = {name: i for i, (name, _) in enumerate(_UNITS)}
_TERM = re.compile(r"(\\d+)(?:\\.(\\d+))?(ms|w|d|h|m|s)")


def parse(s):
    if not isinstance(s, str) or s == "":
        raise ValueError("empty duration")
    if any(ch.isspace() for ch in s):
        raise ValueError("whitespace in duration")
    negative = s.startswith("-")
    body = s[1:] if negative else s
    if body == "" or "-" in body:
        raise ValueError("misplaced sign")
    if body.isdigit():
        total = int(body) * 1000
        return -total if negative else total
    terms = []
    pos = 0
    while pos < len(body):
        m = _TERM.match(body, pos)
        if m is None:
            raise ValueError("bad term at %d" % pos)
        terms.append(m.groups())
        pos = m.end()
    if not terms:
        raise ValueError("no terms")
    ranks = [_RANK[t[2]] for t in terms]
    for i in range(len(ranks) - 1):
        if ranks[i] >= ranks[i + 1]:
            raise ValueError("units out of order or repeated")
    total = 0
    for whole, frac, unit in terms:
        size = _SIZE[unit]
        total += int(whole) * size
        if frac is not None:
            total += int(frac) * size // (10 ** len(frac))
    return -total if negative else total


def render(ms):
    rest = -ms if ms < 0 else ms
    parts = []
    for name, size in _UNITS:
        count, rest = divmod(rest, size)
        parts.append("%d%s" % (count, name))
    return ("-" if ms < 0 else "") + "".join(parts)
''',
)
