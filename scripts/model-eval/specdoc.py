"""The long specification used by tasks 9 and 10 (group E).

Deterministic: no randomness, so every model sees byte-identical text.

Two clauses contradict each other and no others do; the filler is written so
that each numeric obligation names a distinct record class, which is what keeps
an accidental second contradiction out.
"""

# (section number, title, [clause bodies])
_SECTIONS: list[tuple[int, str, list[str]]] = [
    (1, "Scope and interpretation", [
        "This policy governs every record held by the platform on behalf of a tenant, "
        "including records produced by the platform itself in the course of serving that tenant.",
        "Where two clauses of this policy apply to the same record, the more specific clause governs. "
        "A clause is more specific than another when the set of records it describes is a proper subset "
        "of the set the other describes.",
        "Where two clauses are equally specific and cannot both be satisfied, the clause with the higher "
        "number governs.",
        "A duty expressed as MUST is unconditional. A duty expressed as SHOULD may be waived by the "
        "platform operator, and each waiver MUST itself be recorded as an operational record of class OP-1.",
        "Times are given in the record's own timezone unless the clause says otherwise. Durations are "
        "counted from the instant the record was written, not the instant the event occurred.",
        "A record is deleted when it can no longer be read through any interface the platform offers. "
        "Overwriting the storage is not required for a record to count as deleted.",
        "The obligations in this policy attach to the platform operator, not to the tenant, except where "
        "a clause names the tenant explicitly.",
        "Nothing in this policy authorises the retention of a record for which no clause states a period.",
    ]),
    (2, "Record classes", [
        "Records of class AU are audit records: they describe an action taken against the control plane "
        "by an identified actor.",
        "Records of class US are usage records: they describe one served inference request and carry no "
        "request or response body.",
        "Records of class SE are session records: they describe an authenticated browser session.",
        "Records of class PT are prompt transcripts: they carry the text a caller sent and the text the "
        "platform returned.",
        "Records of class KB are knowledge base records: they carry documents a tenant uploaded and the "
        "passages derived from them.",
        "Records of class OP are operational records: they describe an action taken by the platform "
        "operator that is not attributable to a tenant.",
        "Records of class BK are backup records: they are copies of other records taken for recovery.",
        "A record belongs to exactly one class. Where a record could be read as belonging to two, the "
        "class named by the writing subsystem governs.",
    ]),
    (3, "Audit records", [
        "Every action against the control plane MUST produce a record of class AU before the action's "
        "effect is visible to any other caller.",
        "An AU record MUST carry the actor identifier, the action name, the outcome, and the instant the "
        "action completed.",
        "An AU record MUST NOT carry a credential, a credential fragment, or any value from which a "
        "credential could be reconstructed.",
        "An AU record describing a refused authorization MUST carry the capability that was demanded, so "
        "that a refusal can be told from an absence.",
        "AU records are append only. A correction is written as a further AU record naming the record it "
        "corrects; the original is never edited.",
        "Where an AU record cannot be written, the action it would have described MUST be refused.",
        "An AU record whose action names a tenant is a tenant-scoped audit record. "
        "Tenant-scoped audit records MUST be retained for at least 400 days.",
        "An AU record whose action names no tenant is a platform audit record, and MUST be retained for "
        "at least 30 days.",
        "AU records MUST be readable by an administrator of the tenant they name, and by no other tenant.",
    ]),
    (4, "Usage records", [
        "A US record MUST be written for every request that reached a runtime, including a request whose "
        "generation was cancelled by the caller.",
        "A US record MUST carry the prompt token count and the completion token count as the runtime "
        "reported them, not as the platform estimated them.",
        "Where a runtime reports no token count, the US record MUST carry a null count rather than a zero.",
        "US records MUST be retained for at least 180 days so that a billing dispute can be settled.",
        "A US record MUST NOT be amended after the billing period it falls in has closed.",
        "Aggregates derived from US records are themselves records of class OP, and this policy's limits "
        "on US records do not reach them.",
        "A US record MUST carry the capability the request was routed under, and MUST NOT carry the "
        "identifier of the key that authorised it.",
        "Where a request is refused before it reaches a runtime, no US record is written.",
    ]),
    (5, "Session records", [
        "An SE record MUST be destroyed when the session it describes ends, whether the session ended by "
        "sign-out, by expiry, or by invalidation.",
        "An SE record MUST NOT outlive its session by more than 60 seconds.",
        "An SE record MUST carry no more of the actor's identity than the identifier needed to resolve it.",
        "Every credential change MUST invalidate every SE record belonging to that actor, including the "
        "session that made the change.",
        "An SE record MUST be held in a store that survives neither a host restart nor a deployment.",
        "The platform MUST NOT reconstruct an ended session from a BK record.",
        "An SE record MUST carry the instant of its last use, and that instant MUST be updated on every "
        "authenticated request.",
        "Where the session store is unreachable, every request depending on a session MUST be refused "
        "rather than served unauthenticated.",
        "An SE record MUST NOT be copied into a BK record.",
    ]),
    (6, "Prompt transcripts", [
        "A PT record is written only where the tenant has enabled transcripts for the capability in "
        "question, and the setting MUST default to disabled.",
        "A PT record MUST be readable only by an administrator of the tenant that produced it.",
        "A PT record MUST carry the model reference that produced the response, so that a transcript can "
        "be attributed after a model is retired.",
        "PT records MUST be retained for no more than 30 days, and the platform MUST delete them without "
        "being asked.",
        "A tenant MAY request the deletion of a PT record before the period in clause 6.4 elapses, and the "
        "deletion MUST take effect within 24 hours.",
        "A PT record MUST NOT be used to train, tune, or evaluate any model.",
        "Where transcripts are disabled while records exist, the existing records MUST be deleted within "
        "24 hours of the setting changing.",
        "A PT record MUST NOT be copied into a BK record.",
    ]),
    (7, "Knowledge base records", [
        "A KB record is written when a tenant uploads a document, and one further KB record is written for "
        "each passage derived from it.",
        "A KB record MUST carry the identifier of the document it derives from, so that deleting a "
        "document reaches its passages.",
        "Deleting a document MUST delete every passage derived from it within 60 seconds.",
        "KB records MUST be retained for as long as the tenant that owns them exists, and no longer.",
        "A KB record MUST NOT be readable across tenants, including through a search that scores it.",
        "Where a tenant is deleted, its KB records MUST be deleted within 7 days.",
        "An embedding derived from a KB record is itself a KB record.",
        "A KB record MUST carry the content type as it was declared at upload, and the platform MUST NOT "
        "infer one where the declaration is absent.",
    ]),
    (8, "Backups", [
        "A BK record MUST be encrypted at rest with a key the platform can revoke independently of the "
        "storage it sits on.",
        "A BK record MUST be retained for no more than 35 days.",
        "A BK record MUST NOT be restored into production without an OP record naming the operator who "
        "authorised the restore.",
        "Where a record has been deleted under this policy, a BK record containing it MUST NOT be used to "
        "return it to service.",
        "Backups MUST be taken at least daily, and a failed backup MUST produce an OP record.",
        "A BK record MUST carry the instant the copy was taken, not the instant it was written.",
        "The platform MUST verify at least one BK record per calendar month by restoring it into an "
        "environment that serves no tenant.",
        "A BK record MUST NOT be copied outside the region it was taken in.",
    ]),
    (9, "Tenant lifecycle", [
        "A tenant is deleted when its administrator requests deletion and the request has been confirmed "
        "through a second factor.",
        "Where a tenant is deleted, every record naming it MUST enter the purge process within 24 hours.",
        "The purge process MUST NOT begin before the confirmation in clause 9.1 is recorded as an AU "
        "record.",
        "A record belonging to a deleted tenant MUST be purged within 90 days of the deletion, whatever "
        "period its class would otherwise carry.",
        "Where a tenant is deleted, its API keys MUST be revoked before any record is purged, so that no "
        "request can write a new record into the purge window.",
        "A tenant MAY be restored within 14 days of deletion, and the purge process MUST be suspended for "
        "that period unless the tenant asked for immediate purge or a clause of this policy sets a "
        "shorter period for the record's class.",
        "Records of class AU describing the deletion itself are platform audit records and survive the "
        "purge.",
        "A record belonging to a deleted tenant and held in the EU region MUST be purged within 30 days "
        "of the deletion.",
        "Where a tenant is deleted while a request it authorised is still being served, the request MUST "
        "be cancelled rather than allowed to complete.",
    ]),
    (10, "Regions", [
        "Every record carries the region it was first written in, and that region does not change.",
        "A record written in the EU region MUST NOT be read from outside the EU region except by an "
        "administrator of the tenant that owns it.",
        "A tenant MUST be assigned exactly one region at creation, and the assignment MUST NOT change.",
        "Where a runtime in another region would serve a request faster, the request MUST still be served "
        "in the tenant's own region.",
        "Aggregates that cross regions MUST carry no field from which a single record could be identified.",
        "A region MUST be named in every OP record describing storage.",
        "The platform MUST publish the list of regions it operates and the law it holds each under.",
        "Where a region is retired, its records MUST be migrated before the region stops serving, and the "
        "migration MUST produce one OP record per tenant.",
    ]),
    (11, "The audit store", [
        "The audit store holds records of class AU and no other class.",
        "The audit store MUST refuse a write that would overwrite an existing record.",
        "The audit store MUST be readable by the control plane and MUST NOT be writable by the data plane.",
        "A read of the audit store MUST itself produce an AU record where the reader is not the tenant "
        "that owns the records read.",
        "The audit store MUST hold its records in the order they were written, and that order MUST be "
        "recoverable after a restore.",
        "No record in the audit store may be retained beyond the period clause 8.2 sets for a backup "
        "record.",
        "The audit store MUST reject a record whose actor identifier does not resolve, rather than storing "
        "it against an unknown actor.",
        "Where the audit store is full, the platform MUST refuse control plane writes rather than discard "
        "the oldest records.",
        "The audit store MUST be backed up under section 8 like any other store.",
    ]),
    (12, "Access", [
        "Every read of a record MUST be authorised against the capability named for that record's class.",
        "A capability grants a read only within the tenant the actor belongs to.",
        "An actor with no tenant MUST NOT be able to read any tenant-scoped record.",
        "A capability MUST NOT be inferred from another capability the actor holds.",
        "The platform MUST refuse a read it cannot authorise, and MUST NOT return an empty result in place "
        "of a refusal.",
        "A refused read MUST produce an AU record under clause 3.4.",
        "An expired credential MUST be refused before the record it names is located.",
        "Where a capability is revoked, reads in flight MUST be allowed to complete.",
    ]),
    (13, "Deletion mechanics", [
        "A deletion MUST be idempotent: deleting a record that is already deleted MUST succeed.",
        "A deletion MUST NOT leave a passage, an embedding, or an aggregate that would allow the record's "
        "content to be reconstructed.",
        "A deletion MUST produce an AU record naming the record's class but not its content.",
        "Where a deletion fails, it MUST be retried, and a deletion that has failed three times MUST "
        "produce an OP record.",
        "The platform MUST NOT batch deletions in a way that delays any single deletion past the period "
        "its class carries.",
        "A deletion MUST reach every replica before it is reported as complete.",
        "A record under legal hold MUST NOT be deleted, and the hold MUST itself be an OP record naming "
        "the authority that imposed it.",
        "A legal hold MUST NOT extend a period this policy caps, except where the authority that imposed "
        "it has power to require the extension.",
    ]),
    (14, "Reporting", [
        "The platform MUST publish, once per calendar quarter, the count of records deleted under each "
        "clause of this policy.",
        "The report MUST NOT carry a count small enough to identify a single tenant.",
        "The report MUST name every clause the platform failed to satisfy in the period, and the duration "
        "of each failure.",
        "A failure to publish the report is itself an OP record.",
        "The report MUST be retained for 5 years as an OP record, and section 11 does not reach it.",
        "The platform MUST notify a tenant within 72 hours of discovering that a record belonging to that "
        "tenant was retained past its period.",
        "A notification under clause 14.6 MUST name the clause, the period, and the count, and MUST NOT "
        "name another tenant.",
        "Where a failure is discovered by a tenant rather than by the platform, the notification duty is "
        "unchanged.",
    ]),
    (15, "Encryption and keys", [
        "Every record MUST be encrypted in transit between the platform and any caller, and between any "
        "two components of the platform that do not share a host.",
        "A key used to encrypt records of one tenant MUST NOT be used to encrypt records of another.",
        "A key MUST be rotated at least once per calendar year, and each rotation MUST produce an OP "
        "record naming the key and the instant.",
        "A retired key MUST be held for as long as any record encrypted under it is held, and destroyed "
        "within 24 hours of the last such record being deleted.",
        "Destroying a key is not a substitute for deleting the records it protects.",
        "A key MUST NOT be written into a record of any class, including an OP record describing its own "
        "rotation.",
        "The platform MUST be able to revoke a key without redeploying the component that uses it.",
        "Where a key is suspected to have been disclosed, every record encrypted under it MUST be "
        "re-encrypted under a new key within 30 days.",
        "A pepper used to derive a credential digest is a key for the purposes of this section.",
    ]),
    (16, "Incidents", [
        "An incident is any event in which a record was read, written, or deleted contrary to this policy.",
        "An incident MUST produce an OP record within 1 hour of being discovered, whatever the hour.",
        "The OP record for an incident MUST name the clause breached, the classes of record reached, and "
        "the tenants affected.",
        "The platform MUST NOT delete or amend a record in order to conceal an incident, and an attempt "
        "to do so is itself an incident.",
        "A tenant affected by an incident MUST be notified within 72 hours of discovery.",
        "An incident affecting records in more than one region MUST be reported separately for each "
        "region.",
        "The platform MUST hold the OP records describing an incident for 5 years, and section 8 does not "
        "shorten that period.",
        "Where an incident is discovered during a restore, the restore MUST be stopped before the records "
        "reach production.",
        "A near miss in which no record was reached is not an incident, but MUST still produce an OP "
        "record.",
    ]),
    (17, "Subprocessors", [
        "A subprocessor is any party outside the platform operator that holds, processes, or can read a "
        "record.",
        "The platform MUST publish the list of subprocessors and the classes of record each may reach.",
        "A subprocessor MUST NOT reach a record of class PT under any circumstance.",
        "A subprocessor MUST be bound to the periods this policy sets for each class it reaches.",
        "Adding a subprocessor MUST produce an OP record and MUST be published before the subprocessor "
        "first reaches a record.",
        "Where a subprocessor is removed, every record it holds MUST be deleted within 30 days and the "
        "deletion MUST be attested.",
        "A subprocessor MUST NOT engage a further subprocessor without the platform operator's written "
        "authorisation, itself an OP record.",
        "The platform operator remains answerable for every duty in this policy that a subprocessor "
        "discharges on its behalf.",
        "A model runtime operated on the platform operator's own hardware is not a subprocessor.",
    ]),
    (18, "Change control", [
        "A change to this policy MUST produce an OP record naming the clauses added, amended, and removed.",
        "A change that shortens a period takes effect immediately for records written after it, and "
        "within 30 days for records already held.",
        "A change that lengthens a period MUST NOT be applied to a record whose period has already "
        "elapsed.",
        "A change MUST be published to every tenant at least 30 days before it takes effect, except where "
        "the change is required by an authority with power to require it.",
        "A clause removed from this policy continues to govern records written while it was in force, "
        "unless the change says otherwise.",
        "The revision marker at the head of this document MUST be advanced by every change.",
        "Where a change would leave a class of record with no stated period, the change MUST NOT take "
        "effect.",
        "A draft of a change is an OP record and MUST NOT be published to a tenant.",
    ]),
]

# The planted contradiction: 3.7 requires >= 400 days for tenant-scoped audit
# records; 11.6 caps everything in the audit store at <= 365 days, and 11.1 puts
# audit records there. No other pair of clauses cannot both be satisfied.
CONTRADICTION = ("3.7", "11.6")

# Task 10's scenario resolves to 9.8: an EU-region record of a deleted tenant is
# a proper subset of "a record belonging to a deleted tenant" (9.4), which is in
# turn a subset of the class periods, so the most specific clause governs.
PRECEDENCE_ANSWER = "9.8"


def render() -> str:
    out = ["DATA RETENTION AND ACCESS POLICY", "Revision 2026-03, numbered clauses.", ""]
    for num, title, clauses in _SECTIONS:
        out.append(f"{num}. {title}")
        for i, body in enumerate(clauses, start=1):
            out.append(f"  {num}.{i} {body}")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    doc = render()
    print(doc)
    print(f"\n--- {len(doc)} chars, ~{len(doc)//4} tokens", flush=True)
