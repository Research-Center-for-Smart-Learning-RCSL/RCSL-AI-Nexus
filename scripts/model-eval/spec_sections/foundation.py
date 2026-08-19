"""Clauses 1-6 of the deterministic evaluation policy."""

FOUNDATION_SECTIONS: list[tuple[int, str, list[str]]] = [
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
    ])
]
