"""S - format-sensitive parsing with dense interacting rules.

`ini_parse` is the widest discriminator in the set: 79/38/54/33 across the four
candidates, and its mechanism is dense interacting boundary rules in a parser.
This group adds two more tasks of the same kind, each with a different format
and a different set of edge cases. The checks are fine-grained (10-15 per
task) so a model that gets one rule wrong scores 0.6 rather than 0.0.
"""

from task_registry import CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# S1 - a non-standard CSV dialect
# --------------------------------------------------------------------------

# The dialect: pipe-delimited, single-quote quoting, doubled single quotes
# for escaping, multi-line fields allowed inside quotes, trailing pipe is
# NOT an empty field (it is the delimiter after the last field), and blank
# lines between records are skipped.
task(
    id="csv_pipe",
    group="S",
    kind="code",
    prompt=(
        "Write a Python function `parse_csv(text: str) -> list[list[str]]` that parses "
        "a non-standard CSV dialect with the following rules:\n\n"
        "1. Fields are delimited by the pipe character `|`.\n"
        "2. A field may be quoted by wrapping it in single quotes `'`. A quoted field "
        "begins with `'` immediately after the delimiter (or at the start of the line) "
        "and ends at the next unescaped `'` that is immediately followed by a pipe, "
        "a newline, or the end of the input.\n"
        "3. Inside a quoted field, a literal single quote is represented by two "
        "consecutive single quotes `''`. Pipes and newlines inside a quoted field are "
        "literal characters, not delimiters.\n"
        "4. Outside a quoted field, characters are taken literally until the next pipe "
        "or newline.\n"
        "5. A trailing pipe at the end of a record does NOT create an empty field — it "
        "is simply the delimiter after the last field. A trailing pipe followed by more "
        "content means there is another field.\n"
        "6. Blank lines (lines containing only whitespace) are skipped entirely and do "
        "not produce records.\n"
        "7. Leading and trailing whitespace in an unquoted field is preserved.\n"
        "8. The function receives a single string and returns a list of records, where "
        "each record is a list of field strings with quoting removed.\n"
        + CODE_SUFFIX
    ),
    setup="",
    checks=[
        ("simple row", """
assert parse_csv('a|b|c') == [['a', 'b', 'c']]
""", 10),
        ("multiple rows", """
assert parse_csv('a|b\\nx|y') == [['a', 'b'], ['x', 'y']]
""", 10),
        ("quoted field with pipe", """
assert parse_csv(\"'hello|world'|plain\") == [['hello|world', 'plain']]
""", 10),
        ("escaped single quotes", """
assert parse_csv(\"'it''s'|ok\") == [[\"it's\", 'ok']]
""", 10),
        ("multi-line quoted field", """
assert parse_csv(\"'line1\\nline2'|after\") == [['line1\\nline2', 'after']]
""", 10),
        ("trailing pipe is not an empty field", """
assert parse_csv('a|b|') == [['a', 'b']]
assert parse_csv('a|b|c|') == [['a', 'b', 'c']]
""", 15),
        ("trailing pipe with content after", """
assert parse_csv('a|b||c') == [['a', 'b', '', 'c']]
""", 10),
        ("blank lines skipped", """
assert parse_csv('a|b\\n\\n  \\nx|y') == [['a', 'b'], ['x', 'y']]
""", 10),
        ("whitespace preserved in unquoted", """
assert parse_csv(' a | b ') == [[' a ', ' b ']]
""", 10),
        ("empty quoted field", """
assert parse_csv(\"''|x\") == [['', 'x']]
""", 10),
        ("quoted field at end with trailing pipe", """
assert parse_csv(\"a|'b'|\") == [['a', 'b']]
""", 10),
        ("empty input", """
assert parse_csv('') == []
assert parse_csv('\\n\\n') == []
""", 10),
    ],
    reference="""
```python
def parse_csv(text):
    records = []
    i = 0
    n = len(text)
    while i < n:
        # Skip blank lines
        j = i
        while j < n and text[j] in ' \\t':
            j += 1
        if j >= n or text[j] == '\\n':
            i = j + 1
            continue
        # Parse one record
        fields = []
        while i < n and text[i] != '\\n':
            if text[i] == "'":
                # Quoted field
                i += 1
                parts = []
                while i < n:
                    if text[i] == "'" and i + 1 < n and text[i + 1] == "'":
                        parts.append("'")
                        i += 2
                    elif text[i] == "'":
                        i += 1  # skip closing quote
                        break
                    else:
                        parts.append(text[i])
                        i += 1
                fields.append(''.join(parts))
                if i < n and text[i] == '|':
                    i += 1
            else:
                j = i
                while j < n and text[j] not in '|\\n':
                    j += 1
                fields.append(text[i:j])
                i = j
                if i < n and text[i] == '|':
                    i += 1
        # Trailing pipe: remove empty last field
        if len(fields) > 1 and fields[-1] == '':
            fields.pop()
        if fields:
            records.append(fields)
        if i < n and text[i] == '\\n':
            i += 1
    return records
```
""",
    wrong="""
```python
def parse_csv(text):
    records = []
    for line in text.split('\\n'):
        if not line.strip():
            continue
        fields = line.split('|')
        record = []
        for f in fields:
            if f.startswith("'") and f.endswith("'"):
                record.append(f[1:-1].replace("''", "'"))
            else:
                record.append(f)
        records.append(record)
    return records
```
""",
)


# --------------------------------------------------------------------------
# S2 - TOML-like duration grammar
# --------------------------------------------------------------------------

# A mini-language for compound durations: "2h30m15s" means 2 hours, 30
# minutes, 15 seconds. Rules that interact: unit suffixes are
# case-insensitive, a bare number with no suffix is seconds, components
# may appear in any order but each unit at most once, and there is an
# overflow rule: 90s is valid and normalised to 1m30s in the output.
task(
    id="duration_parse",
    group="S",
    kind="code",
    prompt=(
        "Write a Python function `parse_duration(s: str) -> dict` that parses a compound "
        "duration string and returns a normalised breakdown.\n\n"
        "Input rules:\n"
        "1. A duration is one or more components concatenated with no separator.\n"
        "2. A component is a non-negative integer followed by a unit suffix: `d` (days), "
        "`h` (hours), `m` (minutes), `s` (seconds). Suffixes are case-insensitive.\n"
        "3. A bare integer with no suffix is treated as seconds.\n"
        "4. Components may appear in any order, but each unit may appear at most once. "
        "If a unit appears more than once, raise `ValueError`.\n"
        "5. Leading and trailing whitespace is stripped. Whitespace between components "
        "is allowed.\n"
        "6. An empty string (after stripping) represents zero.\n\n"
        "Output rules:\n"
        "7. Return a dict with keys `'d'`, `'h'`, `'m'`, `'s'`, each an `int`.\n"
        "8. Normalise: seconds 0-59, minutes 0-59, hours 0-23, days carry the rest. "
        "For example, `90s` becomes `{'d': 0, 'h': 0, 'm': 1, 's': 30}`.\n"
        "9. Each unit in the input is first converted to total seconds, then the total "
        "is normalised. So `1h90m` = 3600 + 5400 = 9000 seconds = "
        "`{'d': 0, 'h': 2, 'm': 30, 's': 0}`.\n"
        + CODE_SUFFIX
    ),
    setup="",
    checks=[
        ("simple HMS", """
assert parse_duration('2h30m15s') == {'d': 0, 'h': 2, 'm': 30, 's': 15}
""", 10),
        ("case insensitive", """
assert parse_duration('1H2M3S') == {'d': 0, 'h': 1, 'm': 2, 's': 3}
assert parse_duration('1h2M3s') == {'d': 0, 'h': 1, 'm': 2, 's': 3}
""", 10),
        ("bare number is seconds", """
assert parse_duration('90') == {'d': 0, 'h': 0, 'm': 1, 's': 30}
""", 10),
        ("overflow normalisation", """
assert parse_duration('90s') == {'d': 0, 'h': 0, 'm': 1, 's': 30}
assert parse_duration('90m') == {'d': 0, 'h': 1, 'm': 30, 's': 0}
assert parse_duration('25h') == {'d': 1, 'h': 1, 'm': 0, 's': 0}
""", 15),
        ("mixed overflow", """
assert parse_duration('1h90m') == {'d': 0, 'h': 2, 'm': 30, 's': 0}
assert parse_duration('1d25h61m61s') == {'d': 2, 'h': 2, 'm': 2, 's': 1}
""", 15),
        ("any order", """
assert parse_duration('30s2h') == {'d': 0, 'h': 2, 'm': 0, 's': 30}
assert parse_duration('15m1d') == {'d': 1, 'h': 0, 'm': 15, 's': 0}
""", 10),
        ("whitespace between components", """
assert parse_duration('  2h  30m  ') == {'d': 0, 'h': 2, 'm': 30, 's': 0}
""", 10),
        ("empty string is zero", """
assert parse_duration('') == {'d': 0, 'h': 0, 'm': 0, 's': 0}
assert parse_duration('   ') == {'d': 0, 'h': 0, 'm': 0, 's': 0}
""", 10),
        ("duplicate unit raises ValueError", """
try:
    parse_duration('1h2h')
    assert False, 'should have raised ValueError'
except ValueError:
    pass
try:
    parse_duration('30s10s')
    assert False, 'should have raised ValueError'
except ValueError:
    pass
""", 15),
        ("zero values", """
assert parse_duration('0h0m0s') == {'d': 0, 'h': 0, 'm': 0, 's': 0}
assert parse_duration('0') == {'d': 0, 'h': 0, 'm': 0, 's': 0}
""", 10),
        ("days alone", """
assert parse_duration('3d') == {'d': 3, 'h': 0, 'm': 0, 's': 0}
""", 10),
        ("large value", """
assert parse_duration('100000') == {'d': 1, 'h': 3, 'm': 46, 's': 40}
""", 10),
    ],
    reference="""
```python
import re

def parse_duration(s):
    s = s.strip()
    if not s:
        return {'d': 0, 'h': 0, 'm': 0, 's': 0}

    units = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    seen = set()
    total = 0
    pos = 0
    found_any = False

    while pos < len(s):
        while pos < len(s) and s[pos] == ' ':
            pos += 1
        if pos >= len(s):
            break
        m = re.match(r'(\\d+)', s[pos:])
        if not m:
            raise ValueError(f'unexpected character at position {pos}')
        num = int(m.group(1))
        pos += len(m.group(1))
        while pos < len(s) and s[pos] == ' ':
            pos += 1
        if pos < len(s) and s[pos].lower() in units:
            unit = s[pos].lower()
            if unit in seen:
                raise ValueError(f'duplicate unit {unit}')
            seen.add(unit)
            total += num * units[unit]
            pos += 1
        else:
            if 's' in seen:
                raise ValueError('duplicate unit s')
            seen.add('s')
            total += num
        found_any = True

    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    return {'d': d, 'h': h, 'm': m, 's': sec}
```
""",
    wrong="""
```python
import re

def parse_duration(s):
    s = s.strip()
    if not s:
        return {'d': 0, 'h': 0, 'm': 0, 's': 0}
    result = {'d': 0, 'h': 0, 'm': 0, 's': 0}
    for m in re.finditer(r'(\\d+)([dhms])?', s, re.I):
        num = int(m.group(1))
        unit = (m.group(2) or 's').lower()
        result[unit] += num
    return result
```
""",
)


# --------------------------------------------------------------------------
# S3 - key-value config with section inheritance
# --------------------------------------------------------------------------

task(
    id="config_inherit",
    group="S",
    kind="code",
    prompt=(
        "Write a Python function `parse_config(text: str) -> dict[str, dict[str, str]]` "
        "that parses a configuration format with the following rules:\n\n"
        "1. A section header is a line of the form `[name]` or `[name : parent]`. "
        "Section names and parent names are stripped of leading/trailing whitespace.\n"
        "2. A key-value line is `key = value`. Both key and value are stripped of "
        "leading/trailing whitespace. Keys are lowercased; values are not.\n"
        "3. A line starting with `#` (after optional whitespace) is a comment and is "
        "ignored.\n"
        "4. Blank lines are ignored.\n"
        "5. Lines before any section header belong to section `'DEFAULT'`.\n"
        "6. If a section names a parent with `: parent`, it inherits all key-value "
        "pairs from the parent section. The child's own keys override inherited ones. "
        "The parent must have been defined earlier in the file; if not, raise "
        "`ValueError`.\n"
        "7. Inheritance is transitive: if C inherits from B and B inherits from A, C "
        "sees A's keys (overridden by B's, then by C's own).\n"
        "8. Every section's keys also inherit from `DEFAULT`, with `DEFAULT` having the "
        "lowest priority (overridden by any named parent, then by the section's own "
        "keys).\n"
        "9. Return a dict mapping section name to a dict of the section's effective "
        "key-value pairs (with all inheritance resolved).\n"
        + CODE_SUFFIX
    ),
    setup="",
    checks=[
        ("simple section", """
r = parse_config('[server]\\nhost = localhost\\nport = 8080')
assert r == {'DEFAULT': {}, 'server': {'host': 'localhost', 'port': '8080'}}
""", 10),
        ("DEFAULT section", """
r = parse_config('timeout = 30\\n[server]\\nhost = localhost')
assert r['DEFAULT'] == {'timeout': '30'}
assert r['server'] == {'timeout': '30', 'host': 'localhost'}
""", 10),
        ("inheritance", """
r = parse_config('[base]\\nhost = 0.0.0.0\\nport = 80\\n[dev : base]\\nport = 8080')
assert r['dev'] == {'host': '0.0.0.0', 'port': '8080'}
""", 15),
        ("transitive inheritance", """
r = parse_config('[a]\\nx = 1\\n[b : a]\\ny = 2\\n[c : b]\\nz = 3')
assert r['c'] == {'x': '1', 'y': '2', 'z': '3'}
""", 15),
        ("DEFAULT + parent + own", """
r = parse_config('color = red\\n[base]\\nsize = 10\\n[child : base]\\nweight = 5')
assert r['child'] == {'color': 'red', 'size': '10', 'weight': '5'}
""", 15),
        ("override priority", """
r = parse_config('x = default\\n[parent]\\nx = parent\\n[child : parent]\\nx = child')
assert r['child']['x'] == 'child'
assert r['parent']['x'] == 'parent'
assert r['DEFAULT']['x'] == 'default'
""", 15),
        ("comments and blanks", """
r = parse_config('# comment\\n\\n[s]\\n  # indented comment\\nk = v')
assert r == {'DEFAULT': {}, 's': {'k': 'v'}}
""", 10),
        ("keys lowercased values not", """
r = parse_config('[s]\\nMyKey = MyValue')
assert r['s'] == {'mykey': 'MyValue'}
""", 10),
        ("whitespace in section header", """
r = parse_config('[ base ]\\nx = 1\\n[ child : base ]\\ny = 2')
assert r['base'] == {'x': '1'}
assert r['child'] == {'x': '1', 'y': '2'}
""", 10),
        ("undefined parent raises", """
try:
    parse_config('[child : nonexistent]\\nx = 1')
    assert False, 'should have raised ValueError'
except ValueError:
    pass
""", 10),
    ],
    reference="""
```python
def parse_config(text):
    sections = {'DEFAULT': {}}
    parents = {}
    current = 'DEFAULT'
    for line in text.split('\\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('[') and stripped.endswith(']'):
            inside = stripped[1:-1]
            if ':' in inside:
                name, _, parent = inside.partition(':')
                name = name.strip()
                parent = parent.strip()
                if parent not in sections:
                    raise ValueError(f'undefined parent {parent}')
                parents[name] = parent
            else:
                name = inside.strip()
            current = name
            if current not in sections:
                sections[current] = {}
        elif '=' in stripped:
            key, _, value = stripped.partition('=')
            sections.setdefault(current, {})[key.strip().lower()] = value.strip()

    def resolve(name, visited=None):
        if visited is None:
            visited = set()
        if name in visited:
            raise ValueError('circular inheritance')
        visited.add(name)
        result = dict(sections.get('DEFAULT', {}))
        if name in parents:
            result.update(resolve(parents[name], visited))
        result.update(sections.get(name, {}))
        return result

    out = {}
    for name in sections:
        if name == 'DEFAULT':
            out[name] = dict(sections[name])
        else:
            out[name] = resolve(name)
    return out
```
""",
    wrong="""
```python
def parse_config(text):
    sections = {'DEFAULT': {}}
    current = 'DEFAULT'
    for line in text.split('\\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('[') and stripped.endswith(']'):
            current = stripped[1:-1].strip()
            sections.setdefault(current, {})
        elif '=' in stripped:
            key, _, value = stripped.partition('=')
            sections[current][key.strip().lower()] = value.strip()
    return sections
```
""",
)
