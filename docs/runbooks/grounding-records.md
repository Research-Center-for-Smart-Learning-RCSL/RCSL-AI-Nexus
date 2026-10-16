# Grounding records and shared knowledge epochs

Grounding stores the canonical rendered system context and bounded citations
with the complete ordered history of user anchors. Each anchor records its raw
conversation prefix hash and insertion index. Later turns replay those bytes
before adding a new anchor. Redis `SET NX` selects one winner when first turns
race. Records expire after 24 hours and are capped at 256 KiB, including
citations; when the chain reaches that cap, existing history is preserved and
additional passages are omitted. Atomic admission also caps live records at
64 per tenant and 256 globally (16 MiB per tenant and 64 MiB globally of record
values, plus bounded key/index overhead). Full quotas preserve existing chains
and still add freshly retrieved context and citations for the current question,
without recording that turn or evicting another conversation's prefix. Such
turns emit `grounding_record_not_stored reason=quota_full` without document or
question content. Retries and later turns may retrieve different context:
prefix stability degrades, but grounding remains available.
Expired quota entries are reclaimed using Redis time in the same Lua operation.
Prefix reuse is therefore bounded by record
retention, unchanged history, selection settings, embedding identity and a
clean current knowledge epoch.

HTTP citation disclosure is separate from the stored chain. All chat routes
deduplicate `X-Knowledge-Sources` by document ID and passage index and cap its
value at 2048 bytes, favoring the most recent citations. Retained entries keep
their original order. `X-Knowledge-Sources-Truncated: true` indicates that
distinct citations were omitted from the header. This leaves room for other
response headers in the documented proxy's 4 KiB header buffer. The complete
stored context and citations still replay into the model's prompt.

Cold lookup scans at most the 256 most recent user anchors in one Redis
round trip and returns only the first stored chain (at most 256 KiB), rather
than fetching every chain. If no chain is retained inside that bound for a
longer conversation, the request uses fresh grounding without recording and
logs `grounding_record_not_stored reason=history_unavailable`. Prefix hashing runs in
one pass. Redis Lua and the development memory adapter use the same
newest-first lookup semantics.

The identity and 128-bit source fence are domain-separated HMACs, keyed with
the server API-key pepper. Canonical JSON field encoding includes tenant,
credential ID, tenant/collection selection, collection ID, bounded `top_k`,
retrieval configuration version, embedding reference and exact weights/vector
space identity, and the validated epoch. Content is never a cache key input.
Rotating the server pepper invalidates records and their fences.

Unrestricted searches use the shared Postgres tenant epoch. Collection
searches use the selected collection's epoch. Every upload, collection creation
or deletion, document deletion and vector index/re-index publication commits
Begin on both scopes before changing content. Request End is committed with
the content transaction; detached publication End commits after Qdrant's
acknowledgement. Lock order is collection then tenant. A reader uses independent
short Postgres transactions before and after retrieval/replay, and discards
cached context if the epoch changes. A dirty epoch disables record creation and
replay only: fresh retrieval remains available. A cache outage falls back to
fresh retrieval; a database outage may leave the chat ungrounded.

## Embedding identity and upgrades

Knowledge ingestion and queries require the same runtime kind, reference and
exact manifest digest as the index. Routing may fail over to another node only
when those identities agree. The expected digest is carried through **every**
embedding batch to the node agent and checked against the actual weights before
dispatch. A changed mutable tag, an unknown manifest, or a sender without
manifest validation refuses the embedding; equal vector dimensions do not
establish compatibility. Secure pinned knowledge embeddings require the node
agent path.

Migration `f2c7d9e40b31` marks tenants with existing documents as
`index_requires_rebuild=true`. This is a **legacy provenance marker**, not a
retrieval or ingestion switch. Existing tenants continue fresh search and
chat grounding through the configured embedder; uploads and document re-indexes
remain available. The first new publication pins future writes and queries but
keeps the legacy marker: it does not prove which model generated old vectors.
Immutable grounding replay waits until a full rebuild verifies the tenant.
Keep the existing embedding routing policy unchanged during this transition.
New empty indexes pin their first verified embedding identity as before.

### Supported recovery command

Run `python -m app.infrastructure.recover_knowledge` from a backend environment
with the admin database and Qdrant credentials and the document storage volume.
`--actor` must name an active `admin` or `tenant_admin`; its tenant is the only
tenant affected. The gateway's database account cannot perform this operation.
The CLI writes the audit and epoch changes in the same transaction. No SQL needs
to be written by the operator.

Read state before deciding on recovery:

```sh
python -m app.infrastructure.recover_knowledge status --actor ADMIN_LOGIN
```

For a failed mutation, first stop **all** writer entrances and detached ingestion
jobs, confirm outstanding Qdrant requests have terminated, and reconcile their
vector/document effects with committed metadata. Then use the epoch from status:

```sh
python -m app.infrastructure.recover_knowledge recover --actor ADMIN_LOGIN \
  --expected-epoch EPOCH --writers-stopped --reason "Verified failed mutation effects"
```

The acknowledgement is an operator assertion, not automatic proof of quiescence.
The command rejects a changed epoch and increments all collection and tenant
epochs while clearing their dirty counters. It records the previous epoch,
dirty count, actor and reason. It preserves the index identity and legacy
provenance marker. Resume entrances after inspecting the resulting status.
No TTL or restart silently declares a mutation complete.

For legacy provenance or a deliberate embedding-model change, take the normal
metadata/document backup, stop all entrances and jobs, and pin the desired
embedding model in its node agent. Inspect status, then run:

```sh
python -m app.infrastructure.recover_knowledge rebuild --actor ADMIN_LOGIN \
  --expected-epoch EPOCH --writers-stopped --reason "Rebuild legacy index with verified embedder"
```

The command checks every document has stored text before deleting any vectors,
marks the tenant `index_rebuilding=true`, drops the entire tenant Qdrant index
(including orphan vectors), and embeds every retained document from stored text.
Each batch carries the exact manifest. Only complete acknowledged publication
clears the legacy marker and all fences and publishes the verified identity.
A per-tenant PostgreSQL advisory lock prevents concurrent rebuild commands.

An explicit rebuild is maintenance: while `index_rebuilding=true`, search and
new indexing refuse to use a partially rebuilt space. A failure leaves that flag
and the dirty fence in place; keep entrances stopped, fix the cause, inspect the
new epoch, and rerun **rebuild**. `recover` refuses to clear an interrupted rebuild.
Missing extracted text must be restored or its document removed deliberately;
no source is silently skipped. Verify retrieval before resuming traffic.

## Deployment and capacity decisions

Deploy updated node agents **before** gateways/admin entrances. Verify their
authenticated `/v1/model-capacity` endpoint returns `manifest_digest`,
`declared_context_length`, and `embedding_manifest_pin: true`. An old agent is
not a compatible pinned-embedding sender. Gateways now explicitly verify this
capability instead of assuming an older agent honours `expected_manifest`.

The gateway caches capacity for 60 seconds per node URL/reference/registered
manifest, with at most 256 entries per adapter. A changed registered manifest
misses immediately; a pull invalidates cached metadata; expiry refreshes changes
made outside the platform. Every inference is still checked by the agent against
its current metadata, and runtime dispatch checks the actual served digest.
A failed metadata refresh fails closed instead of reusing an expired answer.

Unresolved capacity and `context_length=0` registrations are intentionally
refused by this PR. MLX targets without readable declared capacity are also
unsupported by this admission path; node-agent mode already excludes MLX.
Operators relying on direct MLX must defer this rollout until that adapter can
provide capacity. Do not fabricate a declaration from an administrator's input.
The three-times estimate bound retains the legacy Ollama half-window ceiling;
this is deliberately more conservative than `estimate*3 + output < window`.
The HMAC still uses a domain-separated API-key pepper: rotating that secret
invalidates grounding records, so include that cache reset in rotation planning.

## Summary deadlines

The gateway waits at most 30 seconds for a Tier 2 result. Its timeout does not
cancel the agent-owned operation. The agent stops accepting summary output at
its own deadline, continues draining the runtime stream, and records a definite
failed outcome once it sees terminal evidence. It then releases the summary
slot. A concurrent summary receives immediate 503 with `Retry-After`.

There is no reliable Ollama per-operation cancellation acknowledgement in this
protocol; closing a socket would discard evidence. Therefore an ordinary local
deadline does not manufacture `outcome_unknown`. Real transport loss, runtime
EOF without terminal evidence, or loss of the owning process still retains the
existing uncertainty/blocking rules. Runtime transport timeouts remain in force.

## Validation

`test_grounding_replay.py` verifies three append-only turns using the actual
sandboxed ChatML renderer and a real byte-level BPE token sequence, excluding
only final generation framing. It also covers contention, deletion paused after
Begin, cross-collection tenant invalidation, credential/history isolation,
bounded full chains, and server-keyed fence sanitisation. This is structural
prefix evidence, not an Ollama timing benchmark or a proof for every runtime
chat template.

`test_knowledge_epochs.py` exercises real PostgreSQL transactions from Alembic,
including atomic request End, rollback, overlapping writers, tenant isolation,
legacy provenance preservation and a blocked Begin racing a content-row lock. Embedding
identity tests cover compatible failover, changed manifests between resolution
and dispatch, per-batch propagation and context cleanup. Optional runtime prefix
timings require the host's normal owned-window probe procedure.

`test_knowledge_recovery.py` covers audited recovery, stale epochs, tenant/role
checks, audit rollback, complete rebuild and interrupted rebuild refusal.
`test_grounding_cache.py` checks concurrent quotas and expiry against real Redis.
Tier 2 tests drive compaction through the agent and Ollama wire protocol (a
synthetic runtime transport), settle terminal evidence, and verify the cache hit.
Live GPU/Ollama timing is not established by these tests.
