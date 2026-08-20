"""Clauses 7-12 of the deterministic evaluation policy."""

DATA_LIFECYCLE_SECTIONS: list[tuple[int, str, list[str]]] = [
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
    ])
]
