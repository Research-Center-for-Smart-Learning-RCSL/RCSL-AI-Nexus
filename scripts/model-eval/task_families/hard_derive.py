from task_registry import _LCG, CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# K - an operation mix no textbook structure serves directly
# --------------------------------------------------------------------------

# Separates models that derive an invariant from models that reach for a
# remembered structure: the answer is the suffix-maximum stack, and nothing in
# the prompt points at it.
task(
    id="visible_suffix",
    group="K",
    kind="code",
    prompt=(
        "Write a Python class `Ridge` supporting two operations on a growing sequence of "
        "integers.\n\n"
        "`append(x)` appends the integer `x` to the end of the sequence.\n\n"
        "`count_visible(k)` returns how many of the last `k` appended elements are visible. "
        "The element at index `i` is visible when it is strictly greater than the element at "
        "index `j` for every `j > i` in the whole sequence, not merely for the `j` inside the "
        "last `k`. If `k` is greater than the current length of the sequence it means the whole "
        "sequence. If `k` is 0 the result is 0. The sequence may be empty.\n\n"
        "An instance is driven with 200,000 appends interleaved with 200,000 calls to "
        "`count_visible`, whose `k` runs to any value up to the length of the sequence. That "
        "whole sequence of operations must finish within 6 seconds on CPython." + CODE_SUFFIX
    ),
    # The expected total was computed once with the reference implementation and
    # pinned, so scoring a model does not pay to recompute it.
    setup=_LCG + """
_N = 200000
_VALS = _lcg(_N, 20260903, 1000000)
_KS = _lcg(_N, 555, _N)
_EXPECTED = 2181297

def _drive(r):
    total = 0
    for _i in range(_N):
        r.append(_VALS[_i])
        total += r.count_visible(_KS[_i])
    return total
""",
    checks=[
        ("empty sequence", """
_r = Ridge()
assert _r.count_visible(0) == 0
assert _r.count_visible(1) == 0
assert _r.count_visible(10) == 0
""", 15),
        ("single element", """
_r = Ridge()
_r.append(5)
assert _r.count_visible(1) == 1
assert _r.count_visible(4) == 1
""", 15),
        ("strictly increasing", """
_r = Ridge()
for _v in [1,2,3,4,5]:
    _r.append(_v)
assert _r.count_visible(5) == 1
assert _r.count_visible(3) == 1
assert _r.count_visible(1) == 1
""", 15),
        ("strictly decreasing", """
_r = Ridge()
for _v in [5,4,3,2,1]:
    _r.append(_v)
assert _r.count_visible(5) == 5
assert _r.count_visible(2) == 2
""", 15),
        ("all equal", """
_r = Ridge()
for _v in [7,7,7,7]:
    _r.append(_v)
assert _r.count_visible(4) == 1
assert _r.count_visible(2) == 1
assert _r.count_visible(3) == 1
""", 15),
        ("equal elements", """
_r = Ridge()
for _v in [3,1,3,2]:
    _r.append(_v)
assert _r.count_visible(4) == 2, _r.count_visible(4)
_r2 = Ridge()
for _v in [4,4,2]:
    _r2.append(_v)
assert _r2.count_visible(3) == 2, _r2.count_visible(3)
""", 15),
        ("k of zero", """
_r = Ridge()
for _v in [9,8,7]:
    _r.append(_v)
assert _r.count_visible(0) == 0
""", 15),
        ("k of one", """
_r = Ridge()
for _v in [1,9,4]:
    _r.append(_v)
assert _r.count_visible(1) == 1
_r.append(4)
assert _r.count_visible(1) == 1
_r.append(10)
assert _r.count_visible(1) == 1
""", 15),
        ("k beyond the length", """
_r = Ridge()
for _v in [2,9,3,8,1]:
    _r.append(_v)
assert _r.count_visible(5) == 3, _r.count_visible(5)
assert _r.count_visible(500) == 3
assert _r.count_visible(5) == _r.count_visible(99)
""", 15),
        ("window smaller than the sequence", """
_r = Ridge()
for _v in [10,2,9,3,8,1]:
    _r.append(_v)
assert _r.count_visible(6) == 4, _r.count_visible(6)
assert _r.count_visible(3) == 2, _r.count_visible(3)
assert _r.count_visible(4) == 3, _r.count_visible(4)
assert _r.count_visible(2) == 2, _r.count_visible(2)
""", 15),
        ("queries interleaved with appends", """
_r = Ridge()
_seen = []
for _v, _k, _want in [(4,1,1),(4,2,1),(6,2,1),(1,3,2),(1,4,2),(9,5,1),(2,2,2)]:
    _r.append(_v)
    assert _r.count_visible(_k) == _want, (_v, _k, _r.count_visible(_k))
""", 15),
        ("appending after a query", """
_r = Ridge()
for _v in [5,3,1]:
    _r.append(_v)
assert _r.count_visible(3) == 3
_r.append(4)
assert _r.count_visible(4) == 2, _r.count_visible(4)
assert _r.count_visible(2) == 1, _r.count_visible(2)
_r.append(0)
assert _r.count_visible(5) == 3, _r.count_visible(5)
""", 15),
        ("negative and repeated values", """
_r = Ridge()
for _v in [-1,-5,-5,-9,-9,0]:
    _r.append(_v)
assert _r.count_visible(6) == 1, _r.count_visible(6)
_r.append(-2)
assert _r.count_visible(7) == 2, _r.count_visible(7)
assert _r.count_visible(1) == 1
""", 15),
        ("200,000 interleaved ops, correct", """
_got = _drive(Ridge())
assert _got == _EXPECTED, "got %d expected %d" % (_got, _EXPECTED)
""", 90),
        ("200,000 interleaved ops, within budget", """
import time as _t
_r = Ridge()
_t0 = _t.perf_counter()
_drive(_r)
_dt = _t.perf_counter() - _t0
assert _dt < 6.0, "took %.1fs" % _dt
""", 15),
    ],
    reference="""
import bisect

class Ridge:
    def __init__(self):
        self.n = 0
        self.idx = []
        self.val = []

    def append(self, x):
        val = self.val
        while val and val[-1] <= x:
            val.pop()
            self.idx.pop()
        self.idx.append(self.n)
        val.append(x)
        self.n += 1

    def count_visible(self, k):
        if k <= 0:
            return 0
        if k >= self.n:
            return len(self.idx)
        lo = self.n - k
        return len(self.idx) - bisect.bisect_left(self.idx, lo)
""",
    # Correct for every input, and rebuilds the suffix maxima on every query.
    wrong="""
class Ridge:
    def __init__(self):
        self.a = []

    def append(self, x):
        self.a.append(x)

    def count_visible(self, k):
        if k <= 0:
            return 0
        n = len(self.a)
        lo = 0 if k >= n else n - k
        best = None
        count = 0
        for i in range(n - 1, -1, -1):
            v = self.a[i]
            if best is None or v > best:
                best = v
                if i >= lo:
                    count += 1
        return count
""",
)


# --------------------------------------------------------------------------
# Q - dense interacting boundary rules in a single parser
# --------------------------------------------------------------------------

# Separates models that hold ten interacting rules simultaneously from models
# that implement the familiar greedy wrap and lose the rules that cut across it.
task(
    id="text_wrap_exact",
    group="Q",
    kind="code",
    prompt=(
        "Write a Python function `wrap(text, width)` returning a list of strings, the output "
        "lines. Whitespace in `text` consists of spaces and newlines only. The rules are:\n\n"
        "1. If `width` is less than 1, raise `ValueError`.\n"
        "2. If `text` contains no character other than whitespace, return an empty list.\n"
        "3. A line of the input holding no character other than whitespace is a blank line. One "
        "or more consecutive blank lines separate one paragraph from the next, and appear in the "
        "output as exactly one empty string between the two paragraphs' lines. Blank lines "
        "before the first paragraph and after the last produce nothing.\n"
        "4. A single newline within a paragraph is a space.\n"
        "5. A run of two or more spaces between two words becomes one space, except that a run "
        "of two or more spaces following a word whose last character is `.`, `?` or `!` becomes "
        "two spaces.\n"
        "6. A word longer than `width` is split into consecutive pieces of exactly `width` "
        "characters, with a final shorter piece holding the remainder if the word's length is "
        "not a multiple of `width`. Each piece is a separate word of the paragraph, separated "
        "from the next by one space. No other word is split.\n"
        "7. A line break falls only between two words. Each line of a paragraph holds as many "
        "of the paragraph's remaining words as fit in `width` characters, counting the spaces "
        "between them from rule 5, and holds at least one word.\n"
        "8. Every line of a paragraph other than its last is padded to exactly `width` "
        "characters by adding spaces to the gaps between its words. The extra spaces are spread "
        "as evenly as the gaps allow, and when they do not divide evenly the leftmost gaps take "
        "one more each.\n"
        "9. A line holding exactly one word is not padded.\n"
        "10. The last line of a paragraph is not padded.\n"
        "11. No output line begins or ends with a space." + CODE_SUFFIX
    ),
    setup="",
    checks=[
        ("width below one raises", """
for _w in (0, -1, -7):
    try:
        wrap("hello world", _w)
    except ValueError:
        pass
    else:
        raise AssertionError("width %d did not raise ValueError" % _w)
""", 15),
        ("empty and whitespace-only input", """
assert wrap("", 10) == []
assert wrap("   ", 10) == []
assert wrap("\\n\\n  \\n", 10) == []
""", 15),
        ("basic wrap and pad", """
_g = wrap("aaa bbb ccc ddd", 7)
assert _g == ["aaa bbb", "ccc ddd"], _g
_g = wrap("a b c d e f", 5)
assert _g == ["a b c", "d e f"], _g
""", 15),
        ("padding spreads evenly", """
_g = wrap("aa bb cc dddddd", 10)
assert _g == ["aa  bb  cc", "dddddd"], _g
_g = wrap("a b c dddddddd", 9)
assert _g == ["a   b   c", "dddddddd"], _g
_g = wrap("a b c d zzzzzzzzz", 10)
assert _g == ["a  b  c  d", "zzzzzzzzz"], _g
""", 15),
        ("leftmost gaps take the remainder", """
_g = wrap("aa bb cc zzzz", 11)
assert _g == ["aa   bb  cc", "zzzz"], _g
_g = wrap("one two three four five six", 11)
assert _g == ["one     two", "three  four", "five six"], _g
""", 15),
        ("a single-word line is not padded", """
_g = wrap("alpha beta", 6)
assert _g == ["alpha", "beta"], _g
_g = wrap("alpha beta gamma", 7)
assert _g == ["alpha", "beta", "gamma"], _g
""", 15),
        ("the last line is not padded", """
_g = wrap("aa bb cc dd ee", 8)
assert _g == ["aa bb cc", "dd ee"], _g
assert _g[-1] == "dd ee"
""", 15),
        ("space runs collapse", """
_g = wrap("aaa     bbb", 20)
assert _g == ["aaa bbb"], _g
_g = wrap("aa,   bb;   cc", 20)
assert _g == ["aa, bb; cc"], _g
""", 15),
        ("two spaces after sentence punctuation", """
_g = wrap("Go.   Now", 20)
assert _g == ["Go.  Now"], _g
_g = wrap("Go?  Now", 20)
assert _g == ["Go?  Now"], _g
_g = wrap("Go!     Now", 20)
assert _g == ["Go!  Now"], _g
_g = wrap("Go. Now", 20)
assert _g == ["Go. Now"], _g
_g = wrap("Go:   Now", 20)
assert _g == ["Go: Now"], _g
""", 15),
        ("paragraphs are separated by one empty string", """
_g = wrap("aaa bbb\\n\\nccc ddd", 7)
assert _g == ["aaa bbb", "", "ccc ddd"], _g
_g = wrap("aaa\\n\\n\\n\\nbbb", 7)
assert _g == ["aaa", "", "bbb"], _g
_g = wrap("\\n\\naaa\\n\\n", 7)
assert _g == ["aaa"], _g
""", 15),
        ("a single newline is a space", """
_g = wrap("aaa\\nbbb", 20)
assert _g == ["aaa bbb"], _g
_g = wrap("aaa bbb\\nccc ddd", 7)
assert _g == ["aaa bbb", "ccc ddd"], _g
""", 15),
        ("a long word is split", """
_g = wrap("abcdefgh", 3)
assert _g == ["abc", "def", "gh"], _g
_g = wrap("abcdef", 3)
assert _g == ["abc", "def"], _g
_g = wrap("xx abcdefgh", 4)
assert _g == ["xx", "abcd", "efgh"], _g
""", 15),
        ("no line begins or ends with a space", """
_g = wrap("   aaa   bbb   \\n   ccc   ", 9)
assert _g == ["aaa   bbb", "ccc"], _g
for _line in wrap("  one two   three four\\n five six  ", 11):
    assert _line == _line.strip(), repr(_line)
""", 15),
        ("sentence spacing meets a line break", """
_g = wrap("end. next word", 9)
assert _g == ["end. next", "word"], _g
_g = wrap("end.  next word", 9)
assert _g == ["end.", "next word"], _g
_g = wrap("aa end.  bb cc", 10)
assert _g == ["aa    end.", "bb cc"], _g
""", 15),
        ("a split word inside a padded paragraph", """
_g = wrap("aa abcdefghij bb cc", 5)
assert _g == ["aa", "abcde", "fghij", "bb cc"], _g
_g = wrap("aa abcdefg bb cc dd", 5)
assert _g == ["aa", "abcde", "fg bb", "cc dd"], _g
""", 15),
        ("a paragraph that is one line", """
_g = wrap("aa bb", 40)
assert _g == ["aa bb"], _g
_g = wrap("aa bb\\n\\ncc dd ee ff\\n\\ngg", 8)
assert _g == ["aa bb", "", "cc dd ee", "ff", "", "gg"], _g
""", 15),
    ],
    reference="""
def wrap(text, width):
    if width < 1:
        raise ValueError("width must be at least 1")

    paragraphs = []
    current = []
    for raw in text.split("\\n"):
        if raw.strip(" ") == "":
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(raw)
    if current:
        paragraphs.append(current)

    out = []
    for pnum, plines in enumerate(paragraphs):
        s = " ".join(plines).strip(" ")
        words = []
        gaps = []
        i = 0
        n = len(s)
        while i < n:
            j = i
            while j < n and s[j] != " ":
                j += 1
            word = s[i:j]
            k = j
            while k < n and s[k] == " ":
                k += 1
            if k < n:
                run = k - j
                gap = 2 if (run >= 2 and word[-1] in ".?!") else 1
            else:
                gap = None
            # Splitting here, after the gap is read, keeps the run-length rule
            # attached to the original word rather than to its final piece.
            if len(word) > width:
                for p in range(0, len(word) - width + 1, width):
                    piece = word[p:p + width]
                    words.append(piece)
                    gaps.append(1)
                rest = len(word) % width
                if rest:
                    words.append(word[-rest:])
                    if gap is not None:
                        gaps.append(gap)
                elif gap is not None:
                    gaps[-1] = gap
            else:
                words.append(word)
                if gap is not None:
                    gaps.append(gap)
            i = k

        lines = []
        a = 0
        total = len(words)
        while a < total:
            b = a
            used = len(words[a])
            while b + 1 < total and used + gaps[b] + len(words[b + 1]) <= width:
                used += gaps[b] + len(words[b + 1])
                b += 1
            lines.append((a, b))
            a = b + 1

        for num, (a, b) in enumerate(lines):
            if num == len(lines) - 1 or a == b:
                parts = []
                for t in range(a, b):
                    parts.append(words[t])
                    parts.append(" " * gaps[t])
                parts.append(words[b])
                out.append("".join(parts))
                continue
            ngaps = b - a
            used = sum(len(words[t]) for t in range(a, b + 1))
            used += sum(gaps[t] for t in range(a, b))
            share, rem = divmod(width - used, ngaps)
            parts = []
            for t in range(a, b):
                parts.append(words[t])
                parts.append(" " * (gaps[t] + share + (1 if t - a < rem else 0)))
            parts.append(words[b])
            out.append("".join(parts))

        if pnum != len(paragraphs) - 1:
            out.append("")
    return out
""",
    # Pads from the right-hand gaps inward, and lets sentence punctuation
    # collapse like any other space run. Every other rule is honoured.
    wrong="""
def wrap(text, width):
    if width < 1:
        raise ValueError("width must be at least 1")

    paragraphs = []
    current = []
    for raw in text.split("\\n"):
        if raw.strip(" ") == "":
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(raw)
    if current:
        paragraphs.append(current)

    out = []
    for pnum, plines in enumerate(paragraphs):
        raw_words = " ".join(plines).split()
        words = []
        for word in raw_words:
            if len(word) > width:
                for p in range(0, len(word), width):
                    words.append(word[p:p + width])
            else:
                words.append(word)

        lines = []
        a = 0
        total = len(words)
        while a < total:
            b = a
            used = len(words[a])
            while b + 1 < total and used + 1 + len(words[b + 1]) <= width:
                used += 1 + len(words[b + 1])
                b += 1
            lines.append((a, b))
            a = b + 1

        for num, (a, b) in enumerate(lines):
            if num == len(lines) - 1 or a == b:
                out.append(" ".join(words[a:b + 1]))
                continue
            ngaps = b - a
            used = sum(len(words[t]) for t in range(a, b + 1))
            share, rem = divmod(width - used, ngaps)
            parts = []
            for t in range(a, b):
                parts.append(words[t])
                parts.append(" " * (share + (1 if (b - 1 - t) < rem else 0)))
            parts.append(words[b])
            out.append("".join(parts))

        if pnum != len(paragraphs) - 1:
            out.append("")
    return out
""",
)
