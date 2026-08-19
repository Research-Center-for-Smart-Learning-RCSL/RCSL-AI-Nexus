from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


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
