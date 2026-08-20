from task_registry import CODE_SUFFIX

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
