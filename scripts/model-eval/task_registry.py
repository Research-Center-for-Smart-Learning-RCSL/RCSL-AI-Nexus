"""Shared task prompt suffixes and deterministic check fixtures."""

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
