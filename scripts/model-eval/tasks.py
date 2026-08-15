"""The task set from docs/model-evaluation.md section 3.

Sixteen tasks in groups A-H, plus the two anchors. Every task scores itself:
code tasks by running the model's function against checks it never saw, exact
tasks by comparing a normalised final line against one right answer.

Each task carries a `reference` that MUST score full marks and a `wrong` that
MUST NOT, which is how the scorer is validated in both directions before any
model is run (section 4.1).

Code check tuples are (name, source, budget_seconds). Each check gets its own
in-process alarm so that one timing check cannot fail the correctness checks
beside it.
"""

from specdoc import CONTRADICTION, PRECEDENCE_ANSWER, render

CODE_SUFFIX = (
    "\n\nReturn exactly one Python code block containing the complete implementation. "
    "Do not include tests, examples, usage, or explanation outside the code block."
)
EXACT_SUFFIX = (
    "\n\nThink it through, then end your reply with a single line of the form\n"
    "FINAL: <answer>\n"
    "and write nothing after that line."
)

# A deterministic pseudo-random generator, written inline so the checks do not
# depend on any stdlib generator staying stable across versions.
_LCG = """
def _lcg(n, seed, mod):
    out = []
    x = seed
    for _ in range(n):
        x = (x * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        out.append((x >> 33) % mod)
    return out
"""

_MERGE_INV = """
def _ref_inversions(a):
    a = list(a)
    buf = [0] * len(a)
    def sort(lo, hi):
        if hi - lo < 2:
            return 0
        mid = (lo + hi) // 2
        c = sort(lo, mid) + sort(mid, hi)
        i, j, k = lo, mid, lo
        while i < mid and j < hi:
            if a[i] <= a[j]:
                buf[k] = a[i]; i += 1
            else:
                buf[k] = a[j]; j += 1; c += mid - i
            k += 1
        while i < mid:
            buf[k] = a[i]; i += 1; k += 1
        while j < hi:
            buf[k] = a[j]; j += 1; k += 1
        a[lo:hi] = buf[lo:hi]
        return c
    import sys
    sys.setrecursionlimit(100000)
    return sort(0, len(a))
"""

TASKS: list[dict] = []


def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# A - the spec contradicts the famous algorithm
# --------------------------------------------------------------------------

task(
    id="merge_disjoint",
    group="A",
    kind="code",
    prompt=(
        "Write a Python function `merge_disjoint(intervals)`.\n\n"
        "`intervals` is a list of `(start, end)` integer pairs with `start <= end`. "
        "The list is not sorted.\n\n"
        "Merge intervals that overlap, and return the resulting list sorted by start, as a list "
        "of `(start, end)` tuples. Intervals `(a, b)` and `(c, d)` overlap when their "
        "intersection has length greater than zero.\n\n"
        "An empty input returns an empty list." + CODE_SUFFIX
    ),
    checks=[
        ("touching stays split", "assert merge_disjoint([(1,3),(3,5)]) == [(1,3),(3,5)]", 5),
        ("overlap merges", "assert merge_disjoint([(1,4),(2,5)]) == [(1,5)]", 5),
        ("empty", "assert merge_disjoint([]) == []", 5),
        ("unsorted chain", "assert merge_disjoint([(5,7),(1,3),(2,6)]) == [(1,7)]", 5),
        ("containment", "assert merge_disjoint([(1,10),(2,3)]) == [(1,10)]", 5),
        ("touching chain of three", "assert merge_disjoint([(1,2),(2,3),(3,4)]) == [(1,2),(2,3),(3,4)]", 5),
        ("single", "assert merge_disjoint([(4,4)]) == [(4,4)]", 5),
    ],
    reference="""
def merge_disjoint(intervals):
    if not intervals:
        return []
    xs = sorted(tuple(i) for i in intervals)
    out = [list(xs[0])]
    for s, e in xs[1:]:
        if s < out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]
""",
    wrong="""
def merge_disjoint(intervals):
    if not intervals:
        return []
    xs = sorted(tuple(i) for i in intervals)
    out = [list(xs[0])]
    for s, e in xs[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]
""",
)

task(
    id="search_last_rotated",
    group="A",
    kind="code",
    prompt=(
        "Write a Python function `search_last_rotated(nums, target)`.\n\n"
        "`nums` was sorted in ascending order and then rotated left by some unknown amount "
        "(possibly zero). It may contain duplicates, including duplicates that straddle the "
        "rotation point.\n\n"
        "Return the index of the last occurrence of `target` in `nums`. If `target` does not "
        "appear, return `-1`. An empty list returns `-1`."
        + CODE_SUFFIX
    ),
    checks=[
        ("last of a run", "assert search_last_rotated([4,5,6,6,7,0,1,2], 6) == 3", 5),
        ("duplicates across the rotation point", "assert search_last_rotated([2,2,2,0,1,2], 2) == 5", 5),
        ("absent", "assert search_last_rotated([1,3,5], 4) == -1", 5),
        ("empty", "assert search_last_rotated([], 1) == -1", 5),
        ("all equal", "assert search_last_rotated([3,3,3,3], 3) == 3", 5),
        ("target at index 0", "assert search_last_rotated([5,1,2,3,4], 5) == 0", 5),
        ("rotation of zero", "assert search_last_rotated([1,2,3,4,5], 3) == 2", 5),
    ],
    reference="""
def search_last_rotated(nums, target):
    for i in range(len(nums) - 1, -1, -1):
        if nums[i] == target:
            return i
    return -1
""",
    wrong="""
def search_last_rotated(nums, target):
    for i, v in enumerate(nums):
        if v == target:
            return i
    return -1
""",
)

# --------------------------------------------------------------------------
# B - many constraints, one assertion each
# --------------------------------------------------------------------------

task(
    id="rate_limiter",
    group="B",
    kind="code",
    prompt=(
        "Write a Python class `RateLimiter`. Its constructor takes `rate`, `window`, `burst`, "
        "`clock` and `idle_ttl`, in that order. It has two methods: `allow(key)`, returning a "
        "bool, and `key_count()`, returning an int.\n\n"
        "`clock` is a callable returning the current time as a float number of seconds; it is "
        "the only source of time this class may consult. `allow(key)` decides whether one call "
        "against `key` is permitted, and each key is accounted for independently of the others. "
        "It is permitted when both of the following hold at the moment it is asked: fewer than "
        "`rate` calls against that key have been permitted with a timestamp strictly greater "
        "than `now - window`, and fewer than `burst` calls against that key have been permitted "
        "with a timestamp strictly greater than `now - 1.0`. A call that was refused is not a "
        "call that was permitted. `allow` is called from many threads at once and the limits "
        "hold across all of them. Since keys arrive from callers the platform does not control, "
        "a key that has been asked about neither successfully nor unsuccessfully for `idle_ttl` "
        "seconds is forgotten. `key_count()` reports how many keys the limiter is holding."
        + CODE_SUFFIX
    ),
    setup="""
class _Clock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t
""",
    checks=[
        ("steady rate", """
_c = _Clock()
_r = RateLimiter(rate=5, window=10.0, burst=100, clock=_c, idle_ttl=1e9)
assert [_r.allow("a") for _ in range(6)] == [True, True, True, True, True, False]
""", 10),
        ("window slides", """
_c = _Clock()
_r = RateLimiter(rate=2, window=10.0, burst=100, clock=_c, idle_ttl=1e9)
assert _r.allow("a") and _r.allow("a") and not _r.allow("a")
_c.t = 10.5
assert _r.allow("a") is True
""", 10),
        ("per key independence", """
_c = _Clock()
_r = RateLimiter(rate=1, window=10.0, burst=100, clock=_c, idle_ttl=1e9)
assert _r.allow("a") is True
assert _r.allow("a") is False
assert _r.allow("b") is True
""", 10),
        ("burst allowance", """
_c = _Clock()
_r = RateLimiter(rate=100, window=60.0, burst=3, clock=_c, idle_ttl=1e9)
assert [_r.allow("a") for _ in range(4)] == [True, True, True, False]
_c.t = 1.5
assert _r.allow("a") is True
""", 10),
        ("denied calls do not fill the window", """
_c = _Clock()
_r = RateLimiter(rate=2, window=10.0, burst=100, clock=_c, idle_ttl=1e9)
assert _r.allow("a") and _r.allow("a")
for _ in range(20):
    assert _r.allow("a") is False
_c.t = 10.5
assert _r.allow("a") is True and _r.allow("a") is True
""", 10),
        ("injected clock only", """
import time as _time
_real = (_time.time, _time.monotonic, _time.perf_counter)
def _boom(*a, **k):
    raise AssertionError("used a real clock")
_time.time = _boom; _time.monotonic = _boom; _time.perf_counter = _boom
try:
    _c = _Clock()
    _r = RateLimiter(rate=2, window=10.0, burst=100, clock=_c, idle_ttl=1e9)
    _r.allow("a"); _r.allow("a"); _r.allow("a"); _r.key_count()
finally:
    _time.time, _time.monotonic, _time.perf_counter = _real
""", 10),
        ("thread safe", """
import threading as _th
_c = _Clock()
_r = RateLimiter(rate=25, window=1000.0, burst=25, clock=_c, idle_ttl=1e9)
_hits = []
def _worker():
    n = 0
    for _ in range(200):
        if _r.allow("a"):
            n += 1
    _hits.append(n)
_ts = [_th.Thread(target=_worker) for _ in range(8)]
for _t in _ts: _t.start()
for _t in _ts: _t.join()
assert sum(_hits) == 25, f"admitted {sum(_hits)} against a cap of 25"
""", 30),
        ("evicts idle keys", """
_c = _Clock()
_r = RateLimiter(rate=5, window=10.0, burst=100, clock=_c, idle_ttl=60.0)
_r.allow("a"); _r.allow("b")
assert _r.key_count() == 2
_c.t = 30.0
_r.allow("b")
assert _r.key_count() == 2, "neither key is idle yet"
_c.t = 70.0
assert _r.key_count() == 1, "'a' has been idle 70s > 60s and should be gone; 'b' only 40s"
_c.t = 95.0
assert _r.key_count() == 0, "'b' has now been idle 65s > 60s too"
""", 10),
    ],
    reference="""
import threading

class RateLimiter:
    def __init__(self, rate, window, burst, clock, idle_ttl):
        self.rate = rate
        self.window = window
        self.burst = burst
        self.clock = clock
        self.idle_ttl = idle_ttl
        self._hits = {}
        self._last = {}
        self._lock = threading.Lock()

    def _evict(self, now):
        dead = [k for k, t in self._last.items() if now - t >= self.idle_ttl]
        for k in dead:
            self._hits.pop(k, None)
            self._last.pop(k, None)

    def allow(self, key):
        with self._lock:
            now = self.clock()
            self._evict(now)
            hits = [t for t in self._hits.get(key, []) if t > now - self.window]
            self._hits[key] = hits
            self._last[key] = now
            if len(hits) >= self.rate:
                return False
            if len([t for t in hits if t > now - 1.0]) >= self.burst:
                return False
            hits.append(now)
            return True

    def key_count(self):
        with self._lock:
            self._evict(self.clock())
            return len(self._hits)
""",
    # Correct in every respect except that it never forgets a key.
    wrong="""
import threading

class RateLimiter:
    def __init__(self, rate, window, burst, clock, idle_ttl):
        self.rate = rate
        self.window = window
        self.burst = burst
        self.clock = clock
        self.idle_ttl = idle_ttl
        self._hits = {}
        self._last = {}
        self._lock = threading.Lock()

    def allow(self, key):
        with self._lock:
            now = self.clock()
            hits = [t for t in self._hits.get(key, []) if t > now - self.window]
            self._hits[key] = hits
            self._last[key] = now
            if len(hits) >= self.rate:
                return False
            if len([t for t in hits if t > now - 1.0]) >= self.burst:
                return False
            hits.append(now)
            return True

    def key_count(self):
        with self._lock:
            return len(self._hits)
""",
)

task(
    id="retry_deadline",
    group="B",
    kind="code",
    prompt=(
        "Write a Python function named `retry_with_deadline` taking, in this order, the "
        "parameters `fn`, `retry_on`, `total_deadline`, `base_delay`, `clock`, `sleep` and "
        "`rand`. It calls `fn()` and returns its return value.\n\n"
        "`clock` returns the current time as a float number of seconds and `sleep(delay)` waits; "
        "they are the only clock and the only wait this function may use. `retry_on` is a tuple "
        "of exception classes, and an exception that is not an instance of one of them is not "
        "this function's business. The delay before retry number `n`, counting the first retry "
        "as `n = 1`, is `base_delay * (2 ** (n - 1)) * rand()`, where `rand()` returns a float "
        "in `[0.0, 1.0]`.\n\n"
        "What bounds the retrying is time rather than a count of attempts: taking `start` as "
        "`clock()` on entry, a retry is not attempted if the wait preceding it would end at or "
        "after `start + total_deadline`. When there is no attempt left to make, the exception "
        "from the most recent one reaches the caller." + CODE_SUFFIX
    ),
    setup="""
class _Env:
    def __init__(self, rand_value=1.0):
        self.t = 0.0
        self.sleeps = []
        self.attempts = 0
        self.rand_value = rand_value
    def clock(self):
        return self.t
    def sleep(self, d):
        self.sleeps.append(d)
        self.t += d
    def rand(self):
        return self.rand_value

class _Transient(Exception):
    pass

class _Fatal(Exception):
    pass
""",
    checks=[
        ("returns on first success", """
_e = _Env()
def _fn():
    _e.attempts += 1
    return "ok"
assert retry_with_deadline(_fn, (_Transient,), 100.0, 1.0, _e.clock, _e.sleep, _e.rand) == "ok"
assert _e.attempts == 1 and _e.sleeps == []
""", 10),
        ("unlisted exception propagates at once", """
_e = _Env()
def _fn():
    _e.attempts += 1
    raise _Fatal("no")
try:
    retry_with_deadline(_fn, (_Transient,), 100.0, 1.0, _e.clock, _e.sleep, _e.rand)
    raise AssertionError("should have raised")
except _Fatal:
    pass
assert _e.attempts == 1 and _e.sleeps == []
""", 10),
        ("exponential schedule", """
_e = _Env(rand_value=1.0)
_n = [0]
def _fn():
    _n[0] += 1
    if _n[0] < 4:
        raise _Transient("t")
    return "ok"
assert retry_with_deadline(_fn, (_Transient,), 1000.0, 1.0, _e.clock, _e.sleep, _e.rand) == "ok"
assert _e.sleeps == [1.0, 2.0, 4.0], _e.sleeps
""", 10),
        ("jitter stays within bounds", """
_e = _Env(rand_value=0.5)
_n = [0]
def _fn():
    _n[0] += 1
    if _n[0] < 4:
        raise _Transient("t")
    return "ok"
retry_with_deadline(_fn, (_Transient,), 1000.0, 1.0, _e.clock, _e.sleep, _e.rand)
assert _e.sleeps == [0.5, 1.0, 2.0], _e.sleeps
for _i, _d in enumerate(_e.sleeps):
    assert _d <= 1.0 * (2 ** _i) + 1e-9
""", 10),
        ("deadline bounds the attempts", """
_e = _Env(rand_value=1.0)
def _fn():
    _e.attempts += 1
    raise _Transient("t%d" % _e.attempts)
try:
    retry_with_deadline(_fn, (_Transient,), 3.0, 1.0, _e.clock, _e.sleep, _e.rand)
    raise AssertionError("should have raised")
except _Transient:
    pass
assert _e.attempts == 2, "attempts=%d" % _e.attempts
assert _e.t < 3.0
""", 10),
        ("re-raises the last exception", """
_e = _Env(rand_value=1.0)
def _fn():
    _e.attempts += 1
    raise _Transient("attempt-%d" % _e.attempts)
try:
    retry_with_deadline(_fn, (_Transient,), 3.0, 1.0, _e.clock, _e.sleep, _e.rand)
    raise AssertionError("should have raised")
except _Transient as _x:
    assert str(_x) == "attempt-2", str(_x)
""", 10),
        ("no sleep after the final attempt", """
_e = _Env(rand_value=1.0)
def _fn():
    _e.attempts += 1
    raise _Transient("t")
try:
    retry_with_deadline(_fn, (_Transient,), 8.0, 1.0, _e.clock, _e.sleep, _e.rand)
except _Transient:
    pass
assert len(_e.sleeps) == _e.attempts - 1, "%d sleeps for %d attempts" % (len(_e.sleeps), _e.attempts)
""", 10),
        ("injected sleep only", """
import time as _time
_real = _time.sleep
def _boom(*a, **k):
    raise AssertionError("used the real sleep")
_time.sleep = _boom
try:
    _e = _Env()
    _n = [0]
    def _fn():
        _n[0] += 1
        if _n[0] < 3:
            raise _Transient("t")
        return "ok"
    retry_with_deadline(_fn, (_Transient,), 1000.0, 1.0, _e.clock, _e.sleep, _e.rand)
finally:
    _time.sleep = _real
""", 10),
    ],
    reference="""
def retry_with_deadline(fn, retry_on, total_deadline, base_delay, clock, sleep, rand):
    start = clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except BaseException as exc:
            if not isinstance(exc, tuple(retry_on)):
                raise
            last = exc
        delay = base_delay * (2 ** (attempt - 1)) * rand()
        if clock() + delay >= start + total_deadline:
            raise last
        sleep(delay)
""",
    # Sleeps before checking the deadline, so it sleeps after the final attempt.
    wrong="""
def retry_with_deadline(fn, retry_on, total_deadline, base_delay, clock, sleep, rand):
    start = clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except BaseException as exc:
            if not isinstance(exc, tuple(retry_on)):
                raise
            last = exc
        delay = base_delay * (2 ** (attempt - 1)) * rand()
        sleep(delay)
        if clock() >= start + total_deadline:
            raise last
""",
)

# --------------------------------------------------------------------------
# C - a complexity requirement, enforced
# --------------------------------------------------------------------------

task(
    id="count_inversions",
    group="C",
    kind="code",
    prompt=(
        "Write a Python function `count_inversions(nums)` returning the number of pairs "
        "`(i, j)` with `i < j` and `nums[i] > nums[j]`.\n\n"
        "It is called with a list of 200,000 integers and must return within 10 seconds on "
        "CPython. It must not mutate the caller's list." + CODE_SUFFIX
    ),
    # The expected value was computed once with the reference implementation and
    # pinned here, so that scoring a model does not pay for it every time.
    setup=_LCG + """
_BIG = _lcg(200000, 20260815, 1000000)
_BIG_EXPECTED = 9961701822
""",
    checks=[
        ("small cases", """
assert count_inversions([]) == 0
assert count_inversions([1]) == 0
assert count_inversions([1,2,3,4]) == 0
assert count_inversions([4,3,2,1]) == 6
assert count_inversions([2,4,1,3,5]) == 3
""", 15),
        ("duplicates are not inversions", "assert count_inversions([2,2,2,2]) == 0", 15),
        ("does not mutate the input", """
_a = [5,1,4,2,3]
count_inversions(_a)
assert _a == [5,1,4,2,3], _a
""", 15),
        ("200,000 elements, correct", """
_got = count_inversions(list(_BIG))
assert _got == _BIG_EXPECTED, "got %d expected %d" % (_got, _BIG_EXPECTED)
""", 30),
        ("200,000 elements, within budget", """
import time as _t
_t0 = _t.perf_counter()
count_inversions(list(_BIG))
_dt = _t.perf_counter() - _t0
assert _dt < 10.0, "took %.1fs" % _dt
""", 20),
    ],
    reference="""
def count_inversions(nums):
    a = list(nums)
    buf = [0] * len(a)
    def sort(lo, hi):
        if hi - lo < 2:
            return 0
        mid = (lo + hi) // 2
        c = sort(lo, mid) + sort(mid, hi)
        i, j, k = lo, mid, lo
        while i < mid and j < hi:
            if a[i] <= a[j]:
                buf[k] = a[i]; i += 1
            else:
                buf[k] = a[j]; j += 1; c += mid - i
            k += 1
        while i < mid:
            buf[k] = a[i]; i += 1; k += 1
        while j < hi:
            buf[k] = a[j]; j += 1; k += 1
        a[lo:hi] = buf[lo:hi]
        return c
    import sys
    sys.setrecursionlimit(100000)
    return sort(0, len(a))
""",
    # Correct, quadratic. Passes every small check and blows the budget.
    wrong="""
def count_inversions(nums):
    n = len(nums)
    c = 0
    for i in range(n):
        for j in range(i + 1, n):
            if nums[i] > nums[j]:
                c += 1
    return c
""",
)

task(
    id="range_sum_updates",
    group="C",
    kind="code",
    prompt=(
        "Write a Python class `RangeSum`. Its constructor takes `nums`, a list of integers. "
        "`update(i, value)` sets `nums[i]` to `value`. `range_sum(left, right)` returns the sum "
        "of `nums[left]` through `nums[right]`, inclusive of both ends.\n\n"
        "It is built over an array of 100,000 integers and then driven with 100,000 updates "
        "interleaved with 100,000 range queries, whose ranges run to any length up to the whole "
        "array. That whole sequence must finish within 5 seconds on CPython." + CODE_SUFFIX
    ),
    setup=_LCG + """
_N = 100000
_BASE = _lcg(_N, 777, 1000)
_OPS_I = _lcg(200000, 999, _N)
_OPS_V = _lcg(200000, 12345, 1000)
_OPS_R = _lcg(100000, 4242, _N)
_EXPECTED_TOTAL = 1662403692679
""",
    checks=[
        ("small correctness", """
_r = RangeSum([1,2,3,4,5])
assert _r.range_sum(0,4) == 15
assert _r.range_sum(1,3) == 9
assert _r.range_sum(2,2) == 3
_r.update(2, 10)
assert _r.range_sum(0,4) == 22
assert _r.range_sum(2,2) == 10
""", 15),
        ("single element", """
_r = RangeSum([7])
assert _r.range_sum(0,0) == 7
_r.update(0, -3)
assert _r.range_sum(0,0) == -3
""", 15),
        ("repeated updates to one index", """
_r = RangeSum([0,0,0])
for _v in range(5):
    _r.update(1, _v)
assert _r.range_sum(0,2) == 4
""", 15),
        ("100,000 interleaved ops, correct", """
_r = RangeSum(list(_BASE))
_total = 0
for _k in range(100000):
    _r.update(_OPS_I[_k], _OPS_V[_k])
    _l = _OPS_I[100000 + _k]
    _rr = min(_l + _OPS_R[_k], _N - 1)
    _total += _r.range_sum(_l, _rr)
assert _total == _EXPECTED_TOTAL, "got %d expected %d" % (_total, _EXPECTED_TOTAL)
""", 60),
        ("100,000 interleaved ops, within budget", """
import time as _t
_r = RangeSum(list(_BASE))
_t0 = _t.perf_counter()
for _k in range(100000):
    _r.update(_OPS_I[_k], _OPS_V[_k])
    _l = _OPS_I[100000 + _k]
    _rr = min(_l + _OPS_R[_k], _N - 1)
    _r.range_sum(_l, _rr)
_dt = _t.perf_counter() - _t0
assert _dt < 5.0, "took %.1fs" % _dt
""", 12),
    ],
    reference="""
class RangeSum:
    def __init__(self, nums):
        self.n = len(nums)
        self.a = list(nums)
        self.t = [0] * (self.n + 1)
        for i, v in enumerate(nums):
            j = i + 1
            while j <= self.n:
                self.t[j] += v
                j += j & (-j)

    def _prefix(self, i):
        s = 0
        while i > 0:
            s += self.t[i]
            i -= i & (-i)
        return s

    def update(self, i, value):
        delta = value - self.a[i]
        self.a[i] = value
        j = i + 1
        while j <= self.n:
            self.t[j] += delta
            j += j & (-j)

    def range_sum(self, left, right):
        return self._prefix(right + 1) - self._prefix(left)
""",
    # Correct, linear per query.
    wrong="""
class RangeSum:
    def __init__(self, nums):
        self.a = list(nums)

    def update(self, i, value):
        self.a[i] = value

    def range_sum(self, left, right):
        return sum(self.a[left:right + 1])
""",
)

# --------------------------------------------------------------------------
# D - the bug is two levels from the symptom
# --------------------------------------------------------------------------

task(
    id="cache_decorator",
    group="D",
    kind="code",
    prompt=(
        "This memoiser is in production and a caller has reported that a service which was "
        "briefly unavailable now fails permanently, long after the service recovered:\n\n"
        "```python\n"
        "def memoize(fn, cache={}):\n"
        "    def wrapper(*args):\n"
        "        if args not in cache:\n"
        "            try:\n"
        "                cache[args] = fn(*args)\n"
        "            except Exception as exc:\n"
        "                cache[args] = exc\n"
        "        value = cache[args]\n"
        "        if isinstance(value, Exception):\n"
        "            raise value\n"
        "        return value\n"
        "    return wrapper\n"
        "```\n\n"
        "Two tickets are open against it.\n\n"
        "The first says that a lookup which failed once during a five-minute outage has returned "
        "the same error on every call since, including calls made days later, and that "
        "restarting the process is the only thing that clears it.\n\n"
        "The second says that a rates table and a currency table, memoised separately, "
        "occasionally answer with each other's rows.\n\n"
        "Whatever the memoiser does about those, it must still be a memoiser: a repeated call "
        "with arguments that have already been answered must not reach `fn` again.\n\n"
        "Return a corrected `memoize(fn)` taking one argument and no others."
        + CODE_SUFFIX
    ),
    checks=[
        ("caches successes", """
_n = [0]
def _f(x):
    _n[0] += 1
    return x * 2
_m = memoize(_f)
assert _m(3) == 6 and _m(3) == 6
assert _n[0] == 1, "fn called %d times" % _n[0]
""", 10),
        ("distinct arguments cached separately", """
_n = [0]
def _f(x):
    _n[0] += 1
    return x * 2
_m = memoize(_f)
assert _m(1) == 2 and _m(2) == 4 and _m(1) == 2
assert _n[0] == 2, "fn called %d times" % _n[0]
""", 10),
        ("two memoised functions do not collide", """
_a = memoize(lambda x: ("a", x))
_b = memoize(lambda x: ("b", x))
assert _a(1) == ("a", 1)
assert _b(1) == ("b", 1), "second function returned the first one's cached value"
""", 10),
        ("failure propagates", """
def _f(x):
    raise ValueError("down")
_m = memoize(_f)
try:
    _m(1)
    raise AssertionError("should have raised")
except ValueError:
    pass
""", 10),
        ("failure is not cached", """
_n = [0]
def _f(x):
    _n[0] += 1
    if _n[0] == 1:
        raise ValueError("transient")
    return "recovered"
_m = memoize(_f)
try:
    _m(1)
except ValueError:
    pass
assert _m(1) == "recovered", "the failure was cached"
""", 10),
        ("recovery is then cached", """
_n = [0]
def _f(x):
    _n[0] += 1
    if _n[0] == 1:
        raise ValueError("transient")
    return "recovered"
_m = memoize(_f)
try:
    _m(1)
except ValueError:
    pass
_m(1); _m(1)
assert _n[0] == 2, "fn called %d times" % _n[0]
""", 10),
    ],
    reference="""
def memoize(fn):
    cache = {}
    def wrapper(*args):
        if args in cache:
            return cache[args]
        value = fn(*args)
        cache[args] = value
        return value
    return wrapper
""",
    # Fixes the shared default, still caches exceptions.
    wrong="""
def memoize(fn):
    cache = {}
    def wrapper(*args):
        if args not in cache:
            try:
                cache[args] = fn(*args)
            except Exception as exc:
                cache[args] = exc
        value = cache[args]
        if isinstance(value, Exception):
            raise value
        return value
    return wrapper
""",
)

task(
    id="pagination_boundary",
    group="D",
    kind="code",
    prompt=(
        "This function returns the `(start, end)` bounds of each page, with `end` exclusive:\n\n"
        "```python\n"
        "def page_bounds(total, page_size):\n"
        "    if total <= 0 or page_size <= 0:\n"
        "        return []\n"
        "    pages = (total + page_size - 1) // page_size\n"
        "    if total % page_size == 0:\n"
        "        pages -= 1\n"
        "    return [(i * page_size, min((i + 1) * page_size, total)) for i in range(pages)]\n"
        "```\n\n"
        "A report says that the last page of a listing is sometimes missing, and that reducing "
        "the page size by one makes it come back.\n\n"
        "This test fails:\n\n"
        "```python\n"
        "def test_exact_multiple():\n"
        "    assert page_bounds(10, 5) == [(0, 5), (5, 10)]\n"
        "```\n\n"
        "The test is correct and must not be changed. Return the corrected `page_bounds`, which "
        "must produce no page that covers nothing." + CODE_SUFFIX
    ),
    checks=[
        ("the reported failure", "assert page_bounds(10, 5) == [(0, 5), (5, 10)]", 5),
        ("partial final page still works", "assert page_bounds(11, 5) == [(0, 5), (5, 10), (10, 11)]", 5),
        ("empty total", "assert page_bounds(0, 5) == []", 5),
        ("one exact page", "assert page_bounds(5, 5) == [(0, 5)]", 5),
        ("smaller than a page", "assert page_bounds(3, 5) == [(0, 3)]", 5),
        ("no empty trailing page", """
for _t in range(1, 60):
    for _p in range(1, 12):
        _b = page_bounds(_t, _p)
        assert all(_e > _s for _s, _e in _b), (_t, _p, _b)
        assert _b[0][0] == 0 and _b[-1][1] == _t, (_t, _p, _b)
        assert all(_b[_i][1] == _b[_i+1][0] for _i in range(len(_b)-1)), (_t, _p, _b)
""", 10),
        ("a larger exact multiple", """
_b = page_bounds(100, 10)
assert len(_b) == 10 and _b[-1] == (90, 100), _b
""", 5),
    ],
    reference="""
def page_bounds(total, page_size):
    if total <= 0 or page_size <= 0:
        return []
    pages = (total + page_size - 1) // page_size
    return [(i * page_size, min((i + 1) * page_size, total)) for i in range(pages)]
""",
    # Special-cases the reported failure and leaves the bug in place.
    wrong="""
def page_bounds(total, page_size):
    if total <= 0 or page_size <= 0:
        return []
    if total == 10 and page_size == 5:
        return [(0, 5), (5, 10)]
    pages = (total + page_size - 1) // page_size
    if total % page_size == 0:
        pages -= 1
    return [(i * page_size, min((i + 1) * page_size, total)) for i in range(pages)]
""",
)

# --------------------------------------------------------------------------
# E - one contradiction across a long specification
# --------------------------------------------------------------------------

_DOC = render()

task(
    id="spec_contradiction",
    group="E",
    kind="exact",
    prompt=(
        "Read the following policy. Exactly two of its numbered clauses cannot both be satisfied "
        "for the same record. Every other pair of clauses is consistent.\n\n"
        "Identify the two clauses.\n\n"
        "-----\n" + _DOC + "\n-----\n\n"
        "Answer with the two clause numbers, separated by a comma and a space, in ascending "
        "order — for example `2.3, 7.1`." + EXACT_SUFFIX
    ),
    expected=f"{CONTRADICTION[0]}, {CONTRADICTION[1]}",
    reference=f"FINAL: {CONTRADICTION[0]}, {CONTRADICTION[1]}",
    wrong="FINAL: 5.1, 8.2",
)

task(
    id="spec_precedence",
    group="E",
    kind="exact",
    prompt=(
        "Read the following policy, then answer the question after it.\n\n"
        "-----\n" + _DOC + "\n-----\n\n"
        "Scenario. A usage record was written 200 days ago for a tenant whose region is EU. "
        "That tenant was deleted 20 days ago, with the confirmation properly recorded, did not "
        "ask for immediate purge, and has not been restored. A backup taken 10 days ago contains "
        "a copy of the record. The record is under no legal hold.\n\n"
        "Several clauses appear to bear on the instant by which this record must be purged. "
        "Applying the policy's own rules for resolving that, give the number of the **single "
        "clause that governs**.\n\n"
        "Answer with one clause number, for example `4.2`." + EXACT_SUFFIX
    ),
    expected=PRECEDENCE_ANSWER,
    reference=f"FINAL: {PRECEDENCE_ANSWER}",
    wrong="FINAL: 4.4",
)

# --------------------------------------------------------------------------
# F - the right answer is a refusal
# --------------------------------------------------------------------------

task(
    id="insufficient_data",
    group="F",
    kind="exact",
    prompt=(
        "Here is every record the platform holds for March 2026:\n\n"
        "```\n"
        "tenant,requests,errors,tokens_in,tokens_out\n"
        "acme,18420,132,9128441,2044120\n"
        "borealis,9077,8,4410902,1180334\n"
        "cinder,41233,905,20114872,5502991\n"
        "```\n\n"
        "Question: for Borealis in March 2026, what was the mean number of output tokens per "
        "**successful** request, to the nearest whole token?\n\n"
        "Answer with the number if the data above determines it. If the data above does not "
        "determine it, the final line must be exactly:\n"
        "FINAL: INSUFFICIENT_DATA" + EXACT_SUFFIX
    ),
    expected="INSUFFICIENT_DATA",
    reference="FINAL: INSUFFICIENT_DATA",
    wrong="FINAL: 130",
)

task(
    id="ambiguous_requirement",
    group="F",
    kind="exact",
    prompt=(
        "A colleague sends you this specification and asks you to implement it:\n\n"
        "> Write `split_budget(total, shares)`. `total` is a non-negative integer and `shares` is "
        "> a list of positive integers. Divide `total` among `len(shares)` recipients in "
        "> proportion to `shares`, returning a list of **integers** that sums to exactly `total`.\n\n"
        "Decide whether this specification determines the output for every valid input.\n\n"
        "If it does, answer `FINAL: DETERMINED`.\n\n"
        "If it does not — if there is a valid input for which two different return values both "
        "satisfy every word of it — do not pick a reading. Answer exactly:\n"
        "FINAL: AMBIGUOUS" + EXACT_SUFFIX
    ),
    expected="AMBIGUOUS",
    reference="FINAL: AMBIGUOUS",
    wrong="FINAL: DETERMINED",
)

# --------------------------------------------------------------------------
# G - multi-hop arithmetic with a unit change
# --------------------------------------------------------------------------

task(
    id="capacity_chain",
    group="G",
    kind="exact",
    prompt=(
        "A cluster has 8 nodes. Each node has 64 GiB of unified memory.\n\n"
        "1. On every node, 12 GiB is reserved for the operating system and containers and is "
        "never available to the model runtime.\n"
        "2. Of the memory that remains across the whole cluster, 75% may be allocated to model "
        "weights; the rest is reserved for KV cache.\n"
        "3. Of that weights allocation, 20% is held back as headroom and is not usable.\n"
        "4. Model checkpoint files are measured in GB, where 1 GB is exactly 1,000,000,000 bytes, "
        "while the memory figures above are in GiB, where 1 GiB is exactly 1,073,741,824 bytes.\n"
        "5. The runtime's own working set takes a further 5 GB on every node, and comes out of "
        "what is left after step 3.\n"
        "6. Each checkpoint file is 4.7 GB.\n\n"
        "How many whole checkpoints fit into what remains across the cluster?\n\n"
        "Answer with a single integer." + EXACT_SUFFIX
    ),
    expected="48",
    reference="FINAL: 48",
    wrong="FINAL: 57",
)

task(
    id="retention_window",
    group="G",
    kind="exact",
    prompt=(
        "A record was created at 2026-01-31 22:40 local time in a region whose offset is "
        "UTC+08:00, and that offset does not change during the period in question.\n\n"
        "Apply these rules in order:\n\n"
        "1. The record is retained until the same clock time on the **last day of the following "
        "calendar month**, in the record's own local timezone.\n"
        "2. Express that instant in UTC.\n"
        "3. A policy ceiling applies: no record may be retained more than 30 days from its "
        "creation. If the instant from step 2 is later than the ceiling, the ceiling governs "
        "instead.\n\n"
        "Give the instant at which the record must be deleted, in UTC, in the exact format "
        "`YYYY-MM-DDTHH:MMZ`." + EXACT_SUFFIX
    ),
    expected="2026-02-28T14:40Z",
    reference="FINAL: 2026-02-28T14:40Z",
    wrong="FINAL: 2026-02-28T22:40Z",
)

# --------------------------------------------------------------------------
# H - structured output with interdependent fields
# --------------------------------------------------------------------------

task(
    id="policy_json",
    group="H",
    kind="code",
    prompt=(
        "Emit a single JSON object, and nothing else, describing this retention policy.\n\n"
        "Source data:\n\n"
        "```\n"
        "bucket,days,records\n"
        "sessions,1,412\n"
        "usage,180,690\n"
        "audit,300,301\n"
        "transcripts,30,84\n"
        "```\n\n"
        "The policy window runs from 2026-03-01 to 2026-03-31.\n\n"
        "Rules:\n\n"
        "- The top-level object has the keys `policy_id`, `window`, `buckets`, `total_records`, "
        "and — only under the condition below — `review`.\n"
        "- `policy_id` is the string `RET-2026-03`.\n"
        "- `window` is an object with `starts_on` and `ends_on`, both `YYYY-MM-DD` strings, and "
        "`ends_on` must be strictly later than `starts_on`.\n"
        "- `buckets` is an array of objects with keys `name`, `days`, `records`, one per row of "
        "the source data, in the order given.\n"
        "- `total_records` is an integer and must equal the sum of the `records` fields of "
        "`buckets`.\n"
        "- `review` is an object with a single key `reason` (any string). It must be present if "
        "and only if at least one bucket has `days` greater than 365. If no bucket does, the "
        "`review` key must be absent entirely.\n\n"
        "Return exactly one fenced code block containing the JSON object and nothing else."
        + CODE_SUFFIX.replace("Python code block", "code block").replace(
            "the complete implementation", "the JSON object"
        )
    ),
    kind_hint="json",
    checks=[
        ("parses as one JSON object", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert isinstance(_o, dict), type(_o)
""", 10),
        ("policy_id", """
import json as _j
assert _j.loads(_PAYLOAD)["policy_id"] == "RET-2026-03"
""", 10),
        ("window dates ordered and correct", """
import json as _j
_w = _j.loads(_PAYLOAD)["window"]
assert _w["starts_on"] == "2026-03-01" and _w["ends_on"] == "2026-03-31", _w
assert _w["ends_on"] > _w["starts_on"]
""", 10),
        ("buckets match the source", """
import json as _j
_b = _j.loads(_PAYLOAD)["buckets"]
assert [(x["name"], x["days"], x["records"]) for x in _b] == [
    ("sessions", 1, 412), ("usage", 180, 690), ("audit", 300, 301), ("transcripts", 30, 84)
], _b
""", 10),
        ("total equals the sum of its parts", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert _o["total_records"] == 1487, _o["total_records"]
assert _o["total_records"] == sum(x["records"] for x in _o["buckets"])
""", 10),
        ("review absent because no bucket exceeds 365 days", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert "review" not in _o, "the longest bucket is 300 days, so review must be absent entirely"
""", 10),
        ("no extra top-level keys", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert set(_o) == {"policy_id", "window", "buckets", "total_records"}, sorted(_o)
""", 10),
    ],
    reference='''```json
{"policy_id": "RET-2026-03",
 "window": {"starts_on": "2026-03-01", "ends_on": "2026-03-31"},
 "buckets": [{"name": "sessions", "days": 1, "records": 412},
             {"name": "usage", "days": 180, "records": 690},
             {"name": "audit", "days": 300, "records": 301},
             {"name": "transcripts", "days": 30, "records": 84}],
 "total_records": 1487}
```''',
    wrong='''```json
{"policy_id": "RET-2026-03",
 "window": {"starts_on": "2026-03-01", "ends_on": "2026-03-31"},
 "buckets": [{"name": "sessions", "days": 1, "records": 412},
             {"name": "usage", "days": 180, "records": 690},
             {"name": "audit", "days": 300, "records": 301},
             {"name": "transcripts", "days": 30, "records": 84}],
 "total_records": 1487,
 "review": {"reason": "audit retention is long"}}
```''',
)

task(
    id="csv_reconcile",
    group="H",
    kind="code",
    prompt=(
        "Two systems disagree. Reconcile them and emit a single JSON object.\n\n"
        "Invoiced:\n"
        "```\n"
        "tenant,amount\n"
        "cinder,4120\n"
        "acme,9310\n"
        "borealis,2255\n"
        "dovetail,780\n"
        "```\n\n"
        "Metered:\n"
        "```\n"
        "tenant,amount\n"
        "acme,9310\n"
        "borealis,2401\n"
        "cinder,3998\n"
        "acme,140\n"
        "elm,1500\n"
        "```\n\n"
        "Rules:\n\n"
        "- A tenant may appear on more than one line of a table. Its amount in that table is the "
        "sum of its lines.\n"
        "- Include a row only for a tenant that appears in **both** tables. A tenant in only one "
        "table is excluded entirely.\n"
        "- The top-level object has exactly the keys `rows` and `total_delta`.\n"
        "- `rows` is an array of objects with exactly the keys `tenant`, `invoiced`, `metered`, "
        "`delta`, sorted by `tenant` ascending.\n"
        "- `delta` is `invoiced` minus `metered`.\n"
        "- `total_delta` is the sum of every `delta` in `rows`.\n"
        "- All amounts are integers.\n\n"
        "Return exactly one fenced code block containing the JSON object and nothing else."
        + CODE_SUFFIX.replace("Python code block", "code block").replace(
            "the complete implementation", "the JSON object"
        )
    ),
    kind_hint="json",
    checks=[
        ("parses, exactly two top-level keys", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert set(_o) == {"rows", "total_delta"}, sorted(_o)
""", 10),
        ("only tenants in both tables", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert [r["tenant"] for r in _o["rows"]] == ["acme", "borealis", "cinder"], _o["rows"]
""", 10),
        ("row keys exact", """
import json as _j
_o = _j.loads(_PAYLOAD)
for _r in _o["rows"]:
    assert set(_r) == {"tenant", "invoiced", "metered", "delta"}, sorted(_r)
""", 10),
        ("the repeated line is summed before the join", """
import json as _j
_o = _j.loads(_PAYLOAD)
_by = {r["tenant"]: r for r in _o["rows"]}
assert (_by["acme"]["invoiced"], _by["acme"]["metered"], _by["acme"]["delta"]) == (9310, 9450, -140), _by["acme"]
""", 10),
        ("deltas computed", """
import json as _j
_o = _j.loads(_PAYLOAD)
_by = {r["tenant"]: r for r in _o["rows"]}
assert (_by["borealis"]["invoiced"], _by["borealis"]["metered"], _by["borealis"]["delta"]) == (2255, 2401, -146)
assert (_by["cinder"]["invoiced"], _by["cinder"]["metered"], _by["cinder"]["delta"]) == (4120, 3998, 122)
""", 10),
        ("total_delta is the sum", """
import json as _j
_o = _j.loads(_PAYLOAD)
assert _o["total_delta"] == -164, _o["total_delta"]
assert _o["total_delta"] == sum(r["delta"] for r in _o["rows"])
""", 10),
        ("integers, not strings", """
import json as _j
_o = _j.loads(_PAYLOAD)
for _r in _o["rows"]:
    for _k in ("invoiced", "metered", "delta"):
        assert isinstance(_r[_k], int), (_r["tenant"], _k, type(_r[_k]))
assert isinstance(_o["total_delta"], int)
""", 10),
    ],
    reference='''```json
{"rows": [{"tenant": "acme", "invoiced": 9310, "metered": 9450, "delta": -140},
          {"tenant": "borealis", "invoiced": 2255, "metered": 2401, "delta": -146},
          {"tenant": "cinder", "invoiced": 4120, "metered": 3998, "delta": 122}],
 "total_delta": -164}
```''',
    wrong='''```json
{"rows": [{"tenant": "acme", "invoiced": 9310, "metered": 9310, "delta": 0},
          {"tenant": "borealis", "invoiced": 2255, "metered": 2401, "delta": -146},
          {"tenant": "cinder", "invoiced": 4120, "metered": 3998, "delta": 122}],
 "total_delta": -24}
```''',
)

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


BY_ID = {t["id"]: t for t in TASKS}

if __name__ == "__main__":
    for t in TASKS:
        n = len(t.get("checks", [])) if t["kind"] == "code" else 1
        print(f"{t['group']:6s} {t['id']:22s} {t['kind']:6s} {n:2d} checks")
    print(f"\n{len(TASKS)} tasks")
