from task_registry import CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


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
