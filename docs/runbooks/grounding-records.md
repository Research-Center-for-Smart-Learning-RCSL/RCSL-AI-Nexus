# Grounding records and shared knowledge epochs

Grounding stores the canonical rendered system context and bounded citations
with the complete ordered history of user anchors. Each anchor records its raw
conversation prefix hash and insertion index. Later turns replay those bytes
before adding a new anchor. Redis `SET NX` selects one winner when first turns
race. Records expire after 24 hours and are capped at 256 KiB, including
citations; when the chain reaches that cap, existing history is preserved and
additional passages are omitted. Prefix reuse is therefore bounded by record
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
longer conversation, the request proceeds ungrounded. Prefix hashing runs in
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
all context if the epoch is dirty or changes. A cache/epoch outage degrades
chat to an ungrounded response.

## Embedding identity and upgrades

Knowledge ingestion and queries require the same runtime kind, reference and
exact manifest digest as the index. Routing may fail over to another node only
when those identities agree. The expected digest is carried through **every**
embedding batch to the node agent and checked against the actual weights before
dispatch. A changed mutable tag, an unknown manifest, or a sender without
manifest validation refuses the embedding; equal vector dimensions do not
establish compatibility. Secure pinned knowledge embeddings require the node
agent path.

Migration `f2c7d9e40b31` marks every tenant with existing documents as
`index_requires_rebuild=true`. Older vectors did not retain their generating
model's identity, so their space cannot be inferred from today's embedding
policy. Grounding/search stays unavailable for these indexes, and a new upload
or partial re-index cannot adopt them. Stored documents and extracted text are
retained. An empty new tenant index pins its first verified embedding identity
and later indexers must match it.

To upgrade a legacy tenant or deliberately change its embedding model:

1. Stop and confirm quiescence of **all** knowledge writers/background ingestion
   tasks for that tenant. Confirm the selected embedding model's manifest is
   pinned and its agent checks that manifest. Preserve original documents and
   extracted text; export metadata and take the normal backup first.
2. As the database owner/admin, commit Begin by incrementing `epoch` and
   `mutations_in_progress` in the tenant row and **every** collection row for
   the tenant. Record the maintenance action and evidence of writer quiescence.
   Readers now fail closed during maintenance.
3. Through the authenticated Qdrant maintenance path, delete the **entire**
   `kb_<tenant_id>` Qdrant collection. Require an acknowledged successful delete
   (or confirmed absence). Deleting individual documents while retaining other
   untyped vectors is insufficient. Do not remove document/text storage.
4. In one Postgres transaction, increment both tenant and all collection epochs
   again, clear their `mutations_in_progress` counters, and set the tenant's
   `embedding_identity=NULL, index_requires_rebuild=false`. Clearing pre-existing
   dirty counters requires the same evidence that all old writers are gone and
   their vector effects have been removed. Audit this End.
5. Resume writers and re-index **every** retained document from its stored text.
   The first publication pins the exact space; later publications and queries
   enforce that pin. Verify all ingestion jobs and retrieval quality before
   treating the tenant's knowledge base as fully rebuilt.

## Failed or interrupted mutations

A failed/unknown vector write, crashed writer or rolled-back content transaction
can leave a committed Begin without End. That dirty fence is intentional:
elapsed time, a cache TTL, a restart or observing no active job is not evidence
that external effects have completed. Other tenants and unrelated clean
collection queries remain eligible, while unrestricted queries for the affected
tenant and queries for affected collections omit grounding.

Do not decrement a dirty counter blindly. Confirm the old writer cannot resume,
inspect/reconcile its Qdrant and document-storage effects against committed
metadata, and audit the resolution. For an uncertain vector-space provenance,
use the complete tenant rebuild above. Only then increment the corresponding
epochs and clear the resolved counters in one transaction. No automatic dirty
fence expiry is implemented.

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
legacy-space refusal and a blocked Begin racing a content-row lock. Embedding
identity tests cover compatible failover, changed manifests between resolution
and dispatch, per-batch propagation and context cleanup. Optional runtime prefix
timings require the host's normal owned-window probe procedure.
