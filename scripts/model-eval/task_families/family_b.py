from task_registry import CODE_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


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
