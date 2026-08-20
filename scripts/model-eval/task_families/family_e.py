from specdoc import CONTRADICTION, PRECEDENCE_ANSWER, render
from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


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
