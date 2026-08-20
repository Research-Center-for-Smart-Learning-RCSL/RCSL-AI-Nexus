from task_registry import _LCG, CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


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
