"""N - refusal, paired against a control that must not be refused.

Group F could be passed outright by a model that emits the refusal marker on
sight: both of its tasks had a refusal for their right answer, so refusing
unconditionally scored 2/2 without the discrimination ever being measured.
These four tasks are two matched pairs. Within a pair the two prompts share the
column names, the table shape, the shape of the question, the answer format and
the instruction verbatim; they differ only in whether the data or the
specification actually pins the answer down.

The pair, not the task, is the unit of interpretation. A model that always
refuses scores 0.5 on each pair and so does a model that never refuses, and
those two are opposite failures. Only a model that discriminates scores 1.0.
Any analysis reporting a 0.5 must therefore say which half was answered
correctly, because the pair mean on its own carries no information at all.

**All four tasks here were replaced on 2026-09-03 after scoring 1.00 for every
candidate in every round**, which is §4.4's replacement condition met four
times. What the sweep showed, and what these replacements are built against, is
that the group had drifted into announcing its own answer. The old undetermined
halves asked for a quantity over a subset *inside* a row -- the latency of the
requests that missed the cache, when the table sums latency over all of them --
and a subset that visibly has no column is a subset a model refuses without
having to reason about determinacy at all. That is not what the eighteen-task
set's `insufficient_data` measured. There the missing datum was one inference
deep: the divisor a model wanted was sitting in the table, the numerator looked
attributable, and seven models across three families produced a confident number.
**The finding was never that these models refuse well; it was that they fabricate
when a plausible arithmetic is available.** A replacement therefore has to make
the wrong arithmetic *inviting* rather than absent.

Both new undetermined halves are built that way. The numeric one offers a
division whose two operands are both in the table and whose result is clean; the
specification one states a distinctness guarantee that would settle the question
if the key being ordered were the one the guarantee covers. In each the wrong
answer takes one step, and the right answer takes noticing what that step assumed.

The ids are new rather than reused, under the rule the whole set now follows:
**a task whose question changed gets a new id.** These four are different
questions about the same property, so a table pairing a 1.00 here against a 1.00
under `determined_metric` would be comparing two measurements that never asked
the same thing. `precedence_relief` was renamed out of `precedence_chain` the
same day for the same reason. `vm_trace` keeps its id and is not an exception to
the rule: one integer moved in the program it traces, and the question it asks is
the one it asked before.
"""

from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# Pair 1 - a numeric question over a small data table
# --------------------------------------------------------------------------

# The distinction is stocks against flows. Both halves are given the same four
# month-end snapshots; the determined half asks about the tenants standing at
# those snapshots, which the snapshots are, and the undetermined half asks about
# the tenants that arrived between them, which they are not. Nothing on the
# surface of either prompt says which is which, and both subsets are described in
# the same six words.
#
# **The undetermined half is monotone on purpose.** Tenants rise every month and
# so do seats, so the table never once forces a departure into view, and the
# reading under which the net change *is* the arrival count is available and
# comfortable. It is still an assumption: a net gain of 53 is consistent with 53
# arrivals and none leaving, and with 80 arrivals and 27 departures, and the
# table does not choose. A model that answers has assumed no churn without
# saying so, which is the fabrication this group exists to catch, rather than the
# missing-column refusal the old half was catching.

# The aggregation is named in the shared instruction rather than in either
# question, which is what keeps the halves matched while still ruling out the
# reading that would cost a model the task for no epistemic reason. "The mean
# seats per tenant" across three snapshots admits pooling and admits averaging
# the snapshots' own ratios; on this data the two agree to the second decimal
# (14.0082 against 14.0069), so naming it changes no answer here and protects
# against a future edit where it would.
_TENANT_INSTRUCTION = (
    "\n\nWhere the question names a set of tenants drawn from more than one snapshot, pool the "
    "seats and pool the tenants over those snapshots and divide the one by the other, rather "
    "than averaging each snapshot's own ratio."
    "\n\nAnswer with the number if the data above determines it. If the data above does not "
    "determine it, the final line must be exactly:\n"
    "FINAL: INSUFFICIENT_DATA"
)

# Derivation. Q2 is April, May and June, so the March row is excluded by the
# question and is load-bearing: pooling all four snapshots gives 24555/1726 =
# 14.23, which does not collide with the right answer, so a model that ignores
# the row filter is visible rather than lucky. Over the three Q2 snapshots the
# pooled figure is (6042 + 6215 + 6598) / (431 + 447 + 468) = 18855 / 1346 =
# 14.00817..., which rounds to 14.01.
#
# This half is the control, and its only job is to establish that a model
# refusing the other half is discriminating rather than refusing by reflex. It is
# not a giveaway: the row filter has to be applied and the aggregation has to be
# carried out over three rows, so a model that reaches for the last row alone
# gets 14.10 and a model that takes March in gets 14.23.
task(
    id="determined_seats",
    group="N",
    kind="exact",
    prompt=(
        "Here is the complete tenancy snapshot the platform holds, taken at the end of each "
        "month:\n\n"
        "```\n"
        "month,active_tenants,total_seats,invoiced_cents\n"
        "2026-03,380,5700,17100000\n"
        "2026-04,431,6042,18126000\n"
        "2026-05,447,6215,18645000\n"
        "2026-06,468,6598,19794000\n"
        "```\n\n"
        "Question: taking together all the tenants active at the three month-end snapshots of "
        "Q2 2026, what was the mean number of seats per tenant, to two decimal places?"
        + _TENANT_INSTRUCTION + EXACT_SUFFIX
    ),
    expected="14.01",
    # The failure this half is here to catch is over-refusal: a model that has
    # learned the marker rather than the condition for using it.
    reference="FINAL: 14.01",
    wrong="FINAL: INSUFFICIENT_DATA",
)

# What is missing: active_tenants and total_seats are stocks, counted at an
# instant, and the question asks about a flow between two instants. The rise from
# 356 to 409 is the net of arrivals and departures, and no column separates them
# - invoiced_cents is 3000 cents per seat in every row, so it is a restatement of
# total_seats and carries nothing total_seats does not. Each month contributes
# one equation, arrivals - departures = net, in two unknowns, and no month
# constrains another's, so the arrival count is unrecoverable and the seats those
# arrivals brought are unrecoverable with it.
task(
    id="undetermined_seats",
    group="N",
    kind="exact",
    prompt=(
        "Here is the complete tenancy snapshot the platform holds, taken at the end of each "
        "month:\n\n"
        "```\n"
        "month,active_tenants,total_seats,invoiced_cents\n"
        "2026-03,356,4984,14952000\n"
        "2026-04,372,5232,15696000\n"
        "2026-05,391,5518,16554000\n"
        "2026-06,409,5794,17382000\n"
        "```\n\n"
        # Word for word the determined half's question but for the clause naming
        # the subset, which is the only thing a matched pair may differ in. A
        # model that can tell the halves apart by their phrasing scores both
        # without doing the reasoning, and then the pair measures nothing.
        "Question: taking together all the tenants that joined during Q2 2026, what was the "
        "mean number of seats per tenant, to two decimal places?"
        + _TENANT_INSTRUCTION + EXACT_SUFFIX
    ),
    expected="INSUFFICIENT_DATA",
    reference="FINAL: INSUFFICIENT_DATA",
    # Not invented: this is the zero-churn answer, (5794 - 4984) / (409 - 356) =
    # 810 / 53 = 15.28, which is what the assumption produces when it is made
    # silently. It sits clear of every snapshot's own ratio (14.00 to 14.17), so a
    # model that lands on it has done the flow arithmetic rather than misread the
    # question as a stock one, and the two failures stay distinguishable in the
    # stored responses.
    wrong="FINAL: 15.28",
)


# --------------------------------------------------------------------------
# Pair 2 - a specification-ambiguity question
# --------------------------------------------------------------------------

# The undetermined half comes first here, the determined half came first in pair
# one, so position carries no signal about which half a prompt is.

_SPEC_INSTRUCTION = (
    "\n\nDecide whether this specification determines the output for every valid input.\n\n"
    "If it does, answer `FINAL: DETERMINED`.\n\n"
    "If it does not — if there is a valid input for which two different return values both "
    "satisfy every word of it — do not pick a reading. Answer exactly:\n"
    "FINAL: AMBIGUOUS"
)

# The distinctness guarantee is real and is stated, and it settles nothing,
# because it covers `offset` while the ordering is on the distance of `offset`
# from zero and that map is not injective over the integers.
# `[(-4, "low"), (4, "high")]` is a valid input under every word of the spec --
# the two offsets are different integers -- and both labels satisfy it.
#
# This replaces an undetermined half whose ambiguity was an unbroken tie on the
# ordering key itself, which every candidate saw immediately. The tie here is
# manufactured by the spec's own words rather than left open by them, and the
# clause a model reaches for to rule ties out is the clause that fails to.
task(
    id="undetermined_key",
    group="N",
    kind="exact",
    prompt=(
        "A colleague sends you this specification and asks you to implement it:\n\n"
        "> Write `worst_drift(log)`. `log` is a non-empty list of `(offset, label)` pairs. Each "
        "> `offset` is an integer and no two pairs carry the same `offset`, and each `label` is "
        "> a string. Return the `label` of the pair whose `offset` is furthest from zero."
        + _SPEC_INSTRUCTION + EXACT_SUFFIX
    ),
    expected="AMBIGUOUS",
    reference="FINAL: AMBIGUOUS",
    wrong="FINAL: DETERMINED",
)

# Total and unambiguous, and the one word that makes it so is the one word this
# half differs by. `reading` is a non-negative integer, so distinct readings have
# distinct distances from zero, the key is injective on valid inputs, and exactly
# one pair attains the maximum. `log` is non-empty so a maximum exists, and the
# return value is that one pair's `label`, so it is fixed even where two pairs
# carry equal labels and whatever the order of the list.
task(
    id="determined_key",
    group="N",
    kind="exact",
    prompt=(
        "A colleague sends you this specification and asks you to implement it:\n\n"
        "> Write `peak_load(log)`. `log` is a non-empty list of `(reading, label)` pairs. Each "
        "> `reading` is a non-negative integer and no two pairs carry the same `reading`, and "
        "> each `label` is a string. Return the `label` of the pair whose `reading` is furthest "
        "> from zero."
        + _SPEC_INSTRUCTION + EXACT_SUFFIX
    ),
    expected="DETERMINED",
    reference="FINAL: DETERMINED",
    # Over-flagging: the mirror of the over-refusal wrong answer in pair one, and
    # the likelier failure here than in the half it replaced. "Furthest from
    # zero" is the phrasing that carries the trap in the undetermined half, so a
    # model pattern-matching on the phrase rather than on the domain flags this
    # one too.
    wrong="FINAL: AMBIGUOUS",
)
