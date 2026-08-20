"""Clauses 13-18 of the deterministic evaluation policy."""

OPERATIONS_SECTIONS: list[tuple[int, str, list[str]]] = [
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
    ])
]
