"""Rebuilds of the two mechanisms the first set saturated at 1.00 for every model.

Group L: the original `ledger_replay` applied 36 events under 11 rules and
scored 0.00 for all four candidates even at a 12,288-token budget — honestly
saturated rather than budget-bound, but saturated all the same. This
replacement keeps the compounding-error property (every event depends on the
running balance from the previous one) and the two traps that separated models
in the original (rejected debits, first-of-month fee exemption carry-over),
but the ledger is ten events under five rules and the answer is a single
integer.

Group P replaces "find the two clauses that contradict", which every model
solved by search: the governing rule here is only reachable by walking four
clauses that sit in four different sections and then applying a fifth that
decides between the last two.
"""

from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# L - state replay with compounding balance
# --------------------------------------------------------------------------

# Five rules, ten events. The two traps that separated models in the 36-event
# version are both here: a rejected debit that is not a transaction (rule 3),
# and the first-of-month fee exemption carrying over to the next applied event
# when the first event of the month is rejected (rule 5 interacting with rule
# 3). The compounding is unchanged: every event's fee-or-no-fee decision
# depends on the balance left by every event before it.
_SHORT_LEDGER_RULES = """\
1. The events are applied strictly in the order listed. The balance is carried in whole US \
cents throughout.
2. A DEBIT reduces the balance by its amount. A CREDIT increases the balance by its amount.
3. A DEBIT whose amount is greater than the balance standing immediately before it would be \
applied is not applied. The event is passed over, and it is not a transaction for any \
purpose of these rules.
4. Every applied DEBIT and every applied CREDIT is a transaction and carries a flat service \
fee of 150 cents, taken from the balance immediately after the transaction's own amount has \
been applied.
5. The first applied transaction of each calendar month carries no fee. It is a transaction \
for every other purpose of these rules."""

_SHORT_LEDGER_TABLE = """\
date        event  type    amount
2026-01-05  E01    CREDIT  8000
2026-01-12  E02    DEBIT   4500
2026-01-18  E03    DEBIT   3200
2026-02-03  E04    CREDIT  6000
2026-02-10  E05    DEBIT   7500
2026-02-15  E06    CREDIT  3500
2026-02-22  E07    DEBIT   2800
2026-03-01  E08    DEBIT   4000
2026-03-08  E09    DEBIT   500
2026-03-15  E10    CREDIT  2000"""

task(
    id="ledger_short",
    group="L",
    kind="exact",
    prompt=(
        "A settlement account opens on 2026-01-01 with a balance of 2000 US cents. The events "
        "below are then applied to it under the rules that follow.\n\n"
        "Rules\n\n" + _SHORT_LEDGER_RULES + "\n\n"
        "Events\n\n"
        "```\n" + _SHORT_LEDGER_TABLE + "\n```\n\n"
        "Give the balance after the last event has been applied, in whole US cents, as an "
        "integer with no thousands separator, no decimal point and no currency symbol."
        + EXACT_SUFFIX
    ),
    expected="2100",
    reference="FINAL: 2100",
    # The wrong answer from the designed near-miss: E08 is correctly rejected
    # (4000 > 750), but the model counts the rejected E08 as consuming the
    # first-of-month exemption for March, so E09 pays a fee it does not owe.
    # That one extra 150-cent fee propagates: E09 balance becomes 100 instead of
    # 250, which makes E10's balance 2100 vs 2250 after the credit, and after
    # E10's fee 1950 vs 2100.
    wrong="FINAL: 1950",
)


# --------------------------------------------------------------------------
# P - a governing rule reachable only transitively
# --------------------------------------------------------------------------

# The chain is 4.3 (three reviewers) -> 9.2 (one reviewer, for incident-driven
# changes) -> 12.5 (that relief reaches single-service changes only, and a change
# reaching two or more is approved as 4.3 provides). Three links, sitting in
# sections 4, 9 and 12, and no clause is placed next to the clause it bears on.
#
# **It was five links until 2026-09-03, and five was outside the band in the
# direction that teaches nothing.** The scenario continued 12.5 -> 6.7
# (single-service schema changes take 4.3's number again) -> 2.6 (6.7 and 9.2
# name each other not at all, so the lower-numbered section governs), and scored
# 0.00 for all four candidates. That is a §4.4 replacement on the letter of the
# rule, but the reason to replace it is what the samples showed rather than the
# rule: the incumbent stopped at 9.2 in every round, one link in, so eleven of
# the twelve samples never reached the last two links at all and the task
# measured nothing about them. A set of tasks nobody can start does not say where
# the ceiling is -- it says only that the ceiling is somewhere below the floor.
#
# Three links keeps the mechanism and moves the difficulty to where the failure
# was actually observed: 9.2 is exactly the clause every candidate stopped at, so
# the question is now whether a model that finds the relief goes on to check
# whether the relief reaches it. §7.6 predicted the 40-70% band for this; the
# prediction is on the record and the run will settle it.
#
# The scenario changes in one respect only, so that the shorter chain is the sole
# variable: the change reaches two services rather than one. Everything else --
# the hour, the open severity 1, the release window, the register, the author --
# stands as it did.
_POLICY_SECTIONS: list[tuple[int, str, list[str]]] = [
    (1, "Purpose and application", [
        "This standard governs every change applied to a service the platform operates in "
        "production, including a change applied by automation on a schedule.",
        "A change is any alteration to the code, the configuration, a persisted data schema, or "
        "an infrastructure definition of such a service.",
        "This standard binds the engineering group, the operations rota, and any contractor "
        "engaged to work on a service it governs.",
        "A change to a service that serves no traffic and holds no tenant data is outside this "
        "standard, and the register MUST record the ground on which it was excluded.",
        "A duty expressed as MUST admits no exception except one this standard states in terms.",
        "A duty expressed as SHOULD may be set aside by the engineering lead, and each instance "
        "MUST be entered in the change register.",
        "Times are given in the platform's operating timezone, and a change applied across "
        "midnight is treated as applied at the instant it began.",
        "Nothing in this standard permits a change to be applied for which no clause states an "
        "approval requirement.",
    ]),
    (2, "Interpretation", [
        "A term defined in this standard carries its defined meaning wherever it appears, and "
        "carries no other.",
        "A reference to a clause is a reference to that clause as it stands at the instant the "
        "change is raised.",
        "The singular includes the plural, and a reference to a person includes a reference to "
        "the role that person holds.",
        "A heading is not part of the clause beneath it and does not narrow the clause.",
        "Where a clause states a period, the period runs from the instant the change was raised, "
        "not from the instant it was entered in the register.",
        "Where two clauses of this standard apply to the same change and state different "
        "approval requirements, the clause that names the other governs. Where neither names the "
        "other, the clause standing in the lower-numbered section governs, and where both stand "
        "in the same section, the higher-numbered clause governs.",
        "A clause stating a requirement in addition to the requirement another clause states is "
        "not in conflict with that clause, and both requirements apply.",
        "An example recorded in the change register is not part of this standard and does not "
        "bear on the reading of any clause.",
    ]),
    (3, "Classes of change", [
        "A routine change is one that alters neither a persisted data schema nor an "
        "infrastructure definition, and whose shape has been applied before without incident.",
        "A structural change is one that alters an infrastructure definition, which is the "
        "declaration of the hosts, the networks and the storage a service runs on.",
        "An incident-driven change is one raised while an incident is open, for the purpose of "
        "ending that incident.",
        "A change may fall into more than one class, and every duty each of its classes carries "
        "applies to it.",
        "The class of a change MUST be recorded when the change is raised, and MUST NOT be "
        "altered after the change is applied.",
        "A change that alters only the value of a feature flag is a routine change where the "
        "flag's default value is recorded in the register.",
        "A revert of a change already applied is itself a change and carries the duties of its "
        "own class.",
        "A change applied to a staging environment is not a change for the purposes of this "
        "standard, and the register MUST NOT record it.",
    ]),
    (4, "Review and approval", [
        "Every change MUST be entered in the change register before it is reviewed.",
        "A reviewer MUST have read the change in full, and MUST record the instant at which the "
        "review was completed.",
        "A change to a production service MUST be approved by three named reviewers, no two of "
        "whom belong to the same team, before the change is applied.",
        "An approval lapses where the change is altered after the approval was recorded, and the "
        "review MUST then be taken again.",
        "An approval MUST name the person who gave it, and an approval recorded against a team "
        "rather than against a person is of no effect.",
        "A reviewer MUST NOT approve a change they authored, and MUST NOT approve a change on "
        "behalf of another person.",
        "An approval MUST be recorded in the change register, and a record of approval held "
        "anywhere else is of no effect.",
        "A review that finds a defect MUST record the defect, and the change MUST NOT be applied "
        "until the defect has been answered in the register.",
    ]),
    (5, "Testing and verification", [
        "A change MUST be built and tested from the revision that will be applied, and not from "
        "a revision that resembles it.",
        "The test suite MUST be run in full, and a suite that was run with any test excluded is "
        "not a run of the suite.",
        "A change that alters behaviour a tenant can observe MUST carry a test that would fail "
        "without the change.",
        "A change MUST be applied first to a canary serving no more than five per cent of "
        "traffic, and observed there for at least fifteen minutes.",
        "Where the canary reports an error rate above the rate the service reported before the "
        "change, the change MUST be withdrawn rather than advanced.",
        "A change that alters a dependency version MUST record the version it replaces.",
        "A load test is required where a change alters a query plan, and its result MUST be "
        "recorded in the register.",
        "Verification performed by the author alone does not satisfy this section.",
    ]),
    (6, "Persisted data schemas", [
        "A change that alters a persisted data schema MUST be applied in a form that leaves the "
        "previous form readable until every service that reads it has itself been changed.",
        "A change that alters a persisted data schema MUST carry, in addition to the approvals "
        "any other clause requires, the approval of one member of the data governance group, who "
        "MUST NOT be a person whose approval another clause counts.",
        "A column MUST NOT be dropped by the same change that stops writing to it.",
        "A change that alters a persisted data schema MUST state the number of rows it will "
        "rewrite, and a rewrite of more than ten million rows MUST be applied in batches.",
        "A migration MUST be reversible, or the change MUST record in the register why it is "
        "not.",
        "An index created on a table serving production traffic MUST be created without holding "
        "a write lock on that table.",
        "A change confined to a single service that alters a persisted data schema MUST be "
        "approved by the number of reviewers clause 4.3 requires.",
        "A change that alters a persisted data schema MUST NOT be combined in one change with an "
        "alteration to an infrastructure definition.",
    ]),
    (7, "Service boundaries", [
        "Every service has one owning team, and that team is recorded in the service catalogue.",
        "A change reaches a service where it alters that service's code, that service's "
        "configuration, or the schema of data that service owns.",
        "A change that reaches two or more services MUST record each of them in the register.",
        "A sidecar process deployed alongside a service is part of that service, a change "
        "reaching only that process and the service it accompanies is confined to a single "
        "service, and the configuration of a sidecar process is not an infrastructure "
        "definition.",
        "A shared library is not a service, and a change to a shared library reaches every "
        "service that will be rebuilt against it.",
        "A service MUST NOT read the storage another service owns, and a change that would give "
        "it that access MUST be refused.",
        "Where a service is transferred between teams, the catalogue MUST be amended before the "
        "next change to that service is raised.",
        "A service with no recorded owner MUST NOT receive a change.",
    ]),
    (8, "Release windows", [
        "A scheduled release window runs from 09:00 to 17:00 on a working day, and the window "
        "calendar records which working days carry one.",
        "A change SHOULD be applied within a scheduled release window.",
        "The window calendar MUST be published one calendar quarter before the quarter it "
        "covers.",
        "A window MUST be closed while an incident of severity 1 is open, except to a change "
        "raised for the purpose of ending that incident.",
        "A change applied in the final hour of a window MUST be observed until the window "
        "closes.",
        "A change applied outside a scheduled release window MUST carry, in addition to the "
        "approvals any other clause requires, the approval of one further reviewer drawn from "
        "the operations rota, who MUST NOT be a person whose approval another clause counts.",
        "No window is scheduled on the last working day of a calendar quarter.",
        "A change that has waited more than 30 days for a window MUST be raised again, and the "
        "original entry MUST be closed.",
    ]),
    (9, "Incident-driven changes", [
        "A change raised for the purpose of ending an open incident MUST name that incident in "
        "the register.",
        "Where a change is raised in response to an open incident of severity 1 or of severity "
        "2, the requirement in clause 4.3 is satisfied by one named reviewer.",
        "The severity of an incident is fixed by the incident commander, and MUST NOT be altered "
        "in order to bring a change within a clause of this standard.",
        "An incident-driven change MUST be observed for one hour after it is applied, and the "
        "observation MUST be recorded.",
        "An incident-driven change MUST record the instant the incident was opened and the "
        "instant the change was applied.",
        "A change raised against an incident that has since been closed is not an "
        "incident-driven change.",
        "The postmortem for an incident MUST list every change applied against it, in the order "
        "the changes were applied.",
        "An incident-driven change that does not end the incident MUST be reverted before a "
        "further change is raised against the same incident.",
    ]),
    (10, "Rollback", [
        "Every change MUST carry a recorded means of returning the service to the state it held "
        "before the change was applied.",
        "The means of rollback MUST be exercised in a non-production environment before the "
        "change is applied.",
        "A rollback MUST be capable of completing within fifteen minutes of the decision to "
        "roll back.",
        "The decision to roll back rests with the operations rota, and MUST NOT be reserved to "
        "the change's author.",
        "A rollback MUST be recorded in the register against the change it reverses.",
        "Where a change cannot be rolled back, the register MUST record the point after which "
        "rollback ceases to be possible.",
        "A rollback that fails is an incident, and the duties of section 9 attach to any change "
        "raised against it.",
        "A change MUST NOT depend for its rollback on a second change being applied first.",
    ]),
    (11, "Records and evidence", [
        "The change register is the sole record of the duties this standard imposes, and an "
        "entry in it MUST NOT be deleted.",
        "An entry MUST carry the change's class, its author, its reviewers, and the instant it "
        "was applied.",
        "An entry MUST carry the identifier of the revision that was applied, and that "
        "identifier MUST resolve.",
        "An entry MUST be amended by a further entry naming it, and never by editing the entry "
        "it corrects.",
        "The register MUST be readable by every person this standard binds.",
        "An entry MUST be retained for three years from the instant the change was applied.",
        "Where the register is unreachable, a change MUST NOT be applied, whatever its class.",
        "A quarterly report MUST state the count of changes applied outside a scheduled release "
        "window and the count applied against an open incident.",
    ]),
    (12, "Scope of relief", [
        "A relief this standard states reaches only what the words of the clause stating it "
        "describe, and MUST NOT be extended by analogy to a change the clause does not describe.",
        "A relief MUST NOT be relied on where the condition it rests on arose from an act of the "
        "change's author.",
        "Two reliefs MUST NOT be relied on for the same change unless each names the other.",
        "A relief relied on MUST be named in the register, and a relief not named there is not "
        "relied on.",
        "The relief in clause 9.2 reaches only a change whose effect is confined to a single "
        "service, and a change reaching two or more services is approved as clause 4.3 "
        "provides.",
        "A relief lapses where the change is altered after the relief was named in the register.",
        "The engineering lead MAY refuse a relief for a particular change, and the refusal MUST "
        "be recorded.",
        "A relief this standard states does not reach a duty imposed by a standard other than "
        "this one.",
    ]),
]


def _render_policy() -> str:
    out = ["CHANGE AND DEPLOYMENT STANDARD", "Revision 2026-05, numbered clauses.", ""]
    for number, title, clauses in _POLICY_SECTIONS:
        out.append(f"{number}. {title}")
        for index, body in enumerate(clauses, start=1):
            out.append(f"  {number}.{index} {body}")
        out.append("")
    return "\n".join(out)


_POLICY = _render_policy()

# The id changes with the question, which is the rule this set now follows
# without exception. `vm_trace` kept its id through a difficulty change on the
# same day and was right to: one integer moved in the program it traces, and its
# two scores are two measurements of one question. Nothing that small happened
# here. The scenario's facts changed, the governing clause changed from 6.7 to
# 4.3, and the answer changed from five people to four -- so a table putting
# `precedence_chain` 0.00 next to a later figure under that id would be reading
# two different questions as one series, which is the precise error the stored
# task definitions in `evaluation_task_definitions` were added to make visible
# and which an id is cheaper than a lookup at preventing.
task(
    id="precedence_relief",
    group="P",
    kind="exact",
    prompt=(
        "Read the following standard, then answer the question after it.\n\n"
        "-----\n" + _POLICY + "\n-----\n\n"
        "Scenario. At 02:10 on a Tuesday, while an incident of severity 1 is open, a change is "
        "raised for the purpose of ending that incident. The change alters the code of the "
        "ledger-api service and the configuration of the billing-api service, and reaches "
        "nothing else. It alters no persisted data schema and no infrastructure definition. It "
        "is applied at 02:40 the same day, which falls outside every scheduled release window. "
        "The incident's severity has not been altered, the change's author is not a reviewer, "
        "the register is reachable, and the change was entered in it before review.\n\n"
        "How many people must approve this change before it may be applied, and which single "
        "clause fixes the number of reviewers required under section 4?\n\n"
        # The example's count must not be the answer's count. It was `4, 3.2`
        # against a five-link answer of 5; the three-link answer is 4, so the
        # example moves rather than quietly handing half the answer to a model
        # that copies its shape.
        "Answer with the total count of people, then the clause number, separated by a comma and "
        "a space — for example `6, 3.2`." + EXACT_SUFFIX
    ),
    # Three under 4.3, which 12.5 restores by name once the relief in 9.2 is
    # found not to reach a change touching two services, plus one from the
    # operations rota under 8.6 because the change is applied outside a window --
    # 8.6 requires that reviewer "in addition to the approvals any other clause
    # requires" and bars counting a person another clause already counts, so the
    # two do not overlap. Nothing adds an approval under section 6: the scenario
    # alters no schema, which is the clause that stopped being reachable when the
    # chain came down to three links.
    expected="4, 4.3",
    # The failure the five-link version actually produced, carried over because
    # it is the walk that stops at the relief without asking what the relief
    # reaches: one reviewer under 9.2 plus 8.6's one. The 8.6 approval is the
    # same on either walk, so the two answers differ only in the link at issue.
    wrong="FINAL: 2, 9.2",
    reference="FINAL: 4, 4.3",
)
