"""Rebuilds of the two mechanisms the first set saturated at 1.00 for every model.

Group L replaces the six-step arithmetic chain: the state carried across events
(month, running balance, fee total, transaction count) means a slip at any one
event moves the answer, so the score is no longer a floor of "did the model
manage six steps". Group P replaces "find the two clauses that contradict",
which every model solved by search: the governing rule here is only reachable by
walking four clauses that sit in four different sections and then applying a
fifth that decides between the last two.
"""

from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# L - long-horizon state replay
# --------------------------------------------------------------------------

# The rules are deliberately not grouped by how much work they do: the two that
# separate models (an event passed over under rule 4 consumes nothing, and the
# rule 8 cap is applied at each fee rather than to the month's total) sit among
# the ordinary ones rather than last, so the prompt does not mark its own traps.
_LEDGER_RULES = """\
1. The events are applied strictly in the order listed. The balance is carried in whole US
   cents throughout and is never rounded.
2. An amount whose currency is EUR is converted before the event is applied, at 1.1750 US
   cents to the EUR cent, the converted amount rounded up to the next whole cent where it is
   not already whole. An amount whose currency is USD is used as it stands.
3. A DEBIT reduces the balance by its US cent amount. A CREDIT increases the balance by its
   US cent amount.
4. A DEBIT whose US cent amount is greater than the balance standing immediately before it
   would be applied is not applied. The event is passed over, and it is a transaction for no
   purpose of these rules.
5. Every applied DEBIT and every applied CREDIT is a transaction and carries a service fee.
   The fee is a percentage of that transaction's US cent amount, at the rate selected by the
   balance standing immediately before the amount is applied: 400000 cents or more, 0.35 per
   cent; 150000 to 399999 cents, 0.80 per cent; below 150000 cents, 1.75 per cent. Each fee
   is rounded up to the next whole cent as it is computed.
6. A fee is taken from the balance immediately after the transaction's own amount has been
   applied.
7. The first transaction applied in a calendar month carries no fee. It is a transaction for
   every other purpose of these rules.
8. The fees taken in a calendar month may not exceed 6000 cents in total. The running total
   for a month begins at zero at the first event applied in that month. Where a fee would
   carry the month's total above 6000 cents, only the part of it that brings the total to
   6000 cents is taken.
9. Every fifth transaction, counted from the first transaction of the ledger and continuing
   across month boundaries without interruption, carries a handling charge of 250 cents,
   taken from the balance after that transaction's fee. A handling charge is not a fee and
   does not enter the total in rule 8.
10. An ADJUST event names an earlier transaction and gives a corrected US cent amount for it.
   The named transaction is treated as though it had carried the corrected amount: the
   difference between the original amount and the corrected amount is returned to the balance
   (added, where the named transaction was a DEBIT; taken, where it was a CREDIT), and the
   fee taken for that transaction is recomputed on the corrected amount at the rate that
   transaction's fee was computed at, the difference being returned to the balance. The
   month's total under rule 8 for the month the named transaction falls in is not revisited.
   An ADJUST event is not a transaction: it carries no fee and no handling charge, it does
   not fall under rule 7, and it does not advance the count in rule 9.
11. Every amount in the table is a whole number of minor units of the currency named beside
   it, and the opening balance is a balance for the purposes of rules 4 and 5."""

_LEDGER_TABLE = """\
date        event  type    amount   currency  corrects
2026-01-04  E01    DEBIT   118400   USD
2026-01-07  E02    CREDIT   96500   USD
2026-01-09  E03    DEBIT    74250   EUR
2026-01-13  E04    CREDIT  145900   USD
2026-01-16  E05    DEBIT    62700   USD
2026-01-20  E06    DEBIT   138500   USD
2026-01-23  E07    CREDIT   84300   EUR
2026-01-27  E08    DEBIT    91800   USD
2026-01-30  E09    CREDIT  127400   USD
2026-02-02  E10    CREDIT  158600   USD
2026-02-05  E11    DEBIT   213700   USD
2026-02-09  E12    DEBIT    68950   EUR
2026-02-12  E13    DEBIT    96400   USD
2026-02-16  E14    CREDIT   42300   USD
2026-02-19  E15    DEBIT    57600   USD
2026-02-23  E16    CREDIT  189500   USD
2026-02-25  E17    DEBIT    45900   EUR
2026-02-27  E18    CREDIT   33700   USD
2026-03-02  E19    DEBIT   288400   USD
2026-03-05  E20    CREDIT  174200   USD
2026-03-09  E21    DEBIT    96300   USD
2026-03-12  E22    DEBIT   132750   USD
2026-03-16  E23    CREDIT   78400   EUR
2026-03-19  E24    ADJUST   41900   USD       E13
2026-03-23  E25    DEBIT    64800   USD
2026-03-26  E26    CREDIT  112500   USD
2026-03-30  E27    DEBIT    87650   EUR
2026-04-02  E28    CREDIT  156900   USD
2026-04-06  E29    DEBIT    74300   USD
2026-04-09  E30    DEBIT   119600   USD
2026-04-13  E31    CREDIT   63850   EUR
2026-04-16  E32    DEBIT    48700   USD
2026-04-20  E33    CREDIT  201400   USD
2026-04-23  E34    DEBIT   165300   USD
2026-04-27  E35    CREDIT   57200   EUR
2026-04-30  E36    DEBIT    92450   USD"""

task(
    id="ledger_replay",
    group="L",
    kind="exact",
    prompt=(
        "A settlement account opens on 2026-01-01 with a balance of 342000 US cents. The events "
        "below are then applied to it under the rules that follow.\n\n"
        "Rules\n\n" + _LEDGER_RULES + "\n\n"
        "Events. The amount column of an ADJUST row is the corrected amount, and the corrects "
        "column names the transaction it corrects.\n\n"
        "```\n" + _LEDGER_TABLE + "\n```\n\n"
        "Give the balance after the last event has been applied, in whole US cents, as an "
        "integer with no thousands separator, no decimal point and no currency symbol."
        + EXACT_SUFFIX
    ),
    expected="246769",
    reference="FINAL: 246769",
    # Computed, not invented: the same simulation with rule 4 changed so that a
    # passed-over DEBIT consumes the month's exemption under rule 7. That makes
    # E20 pay a fee it does not owe, and every later rate lookup shifts with it.
    wrong="FINAL: 245582",
)


# --------------------------------------------------------------------------
# P - a governing rule reachable only transitively
# --------------------------------------------------------------------------

# The chain is 4.3 (three reviewers) -> 9.2 (one reviewer, for incident-driven
# changes) -> 12.5 (that relief reaches single-service changes only) -> 6.7
# (single-service schema changes take 4.3's number again) -> 2.6 (6.7 and 9.2
# name each other not at all, so the lower-numbered section governs). Every link
# is worded like the clause beside it, and no clause is placed next to the clause
# it bears on: the five sit in sections 4, 9, 12, 6 and 2 respectively.
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

task(
    id="precedence_chain",
    group="P",
    kind="exact",
    prompt=(
        "Read the following standard, then answer the question after it.\n\n"
        "-----\n" + _POLICY + "\n-----\n\n"
        "Scenario. At 02:10 on a Tuesday, while an incident of severity 1 is open, a change is "
        "raised for the purpose of ending that incident. The change alters the code of the "
        "ledger-api service and the configuration of the sidecar process deployed alongside "
        "ledger-api, and reaches nothing else. It adds a column to a persisted data schema that "
        "ledger-api owns, rewriting no existing rows. It is applied at 02:40 the same day, which "
        "falls outside every scheduled release window. The incident's severity has not been "
        "altered, the change's author is not a reviewer, the register is reachable, and the "
        "change was entered in it before review.\n\n"
        "How many people must approve this change before it may be applied, and which single "
        "clause fixes the number of reviewers required under section 4?\n\n"
        "Answer with the total count of people, then the clause number, separated by a comma and "
        "a space — for example `4, 3.2`." + EXACT_SUFFIX
    ),
    expected="5, 6.7",
    # Stops one link early: it takes 9.2's relief at face value (one reviewer)
    # without reaching 6.7, so it never gets as far as the tie 2.6 decides. The
    # two additional approvals, under 6.2 and 8.6, are the same on either walk.
    wrong="FINAL: 3, 9.2",
    reference="FINAL: 5, 6.7",
)
