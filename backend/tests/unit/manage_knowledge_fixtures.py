"""Knowledge base management and the ingestion job.

The cases worth pinning are the ones a passing happy path would hide: that the
bytes reach storage before a row claims they exist, that deleting removes both,
that a document mid-ingest cannot be pulled out from under its task, and that a
parser failure records a class rather than the parser's own message.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.ingest_document import IngestDocument
from app.application.use_cases.manage_knowledge import ManageKnowledge
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.knowledge import (
    DocumentStatus,
    KnowledgeCollection,
    KnowledgeDocument,
)
from tests.unit.fakes import (
    FakeAudit,
    FakeDocumentState,
    FakeDocumentStorage,
    FakeEmbedder,
    FakeJobs,
    FakeKnowledge,
    FakeParser,
    FakeVectorStore,
)

TENANT = "11111111-1111-1111-1111-111111111111"

ADMIN = Actor(
    id="admin-1",
    display="admin",
    role=Role.ADMIN,
    source="tailnet",
    scopes=frozenset(Scope),
    tenant_id=TENANT,
)

PLAIN_USER = Actor(
    id="u2",
    display="user",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.CHAT_USE}),
    tenant_id=TENANT,
)

COLLECTION = KnowledgeCollection(id="col-1", tenant_id=TENANT, name="Papers")

PDF = b"%PDF-1.7\nbody"


def build(
    *, collections=(COLLECTION,), documents=(), fail_on_put: bool = False
) -> tuple[ManageKnowledge, FakeKnowledge, FakeDocumentStorage, FakeAudit, FakeVectorStore]:
    knowledge = FakeKnowledge(collections, documents)
    storage = FakeDocumentStorage(fail_on_put=fail_on_put)
    vectors = FakeVectorStore()
    audit = FakeAudit()
    return (
        ManageKnowledge(
            knowledge=knowledge,
            storage=storage,
            vectors=vectors,
            authz=RoleAuthorization(),
            audit=audit,
        ),
        knowledge,
        storage,
        audit,
        vectors,
    )


def document(**overrides) -> KnowledgeDocument:
    base = {
        "id": "22222222-2222-2222-2222-222222222222",
        "tenant_id": TENANT,
        "collection_id": "col-1",
        "filename": "paper.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(PDF),
        "status": DocumentStatus.UPLOADED,
    }
    return KnowledgeDocument(**{**base, **overrides})


@dataclass
class Ingestion:
    use_case: IngestDocument
    knowledge: FakeKnowledge
    storage: FakeDocumentStorage
    state: FakeDocumentState
    jobs: FakeJobs
    vectors: FakeVectorStore
    embedder: FakeEmbedder


def build_ingest(
    doc: KnowledgeDocument,
    *,
    parser: FakeParser | None = None,
    embedder: FakeEmbedder | None = None,
    vectors: FakeVectorStore | None = None,
) -> Ingestion:
    knowledge = FakeKnowledge((COLLECTION,), (doc,))
    storage = FakeDocumentStorage()
    storage.originals[doc.id] = PDF
    state = FakeDocumentState(knowledge)
    jobs = FakeJobs()
    store = vectors or FakeVectorStore()
    embed = embedder or FakeEmbedder()
    return Ingestion(
        use_case=IngestDocument(
            state_committer=state,
            storage=storage,
            parser=parser or FakeParser(),
            jobs=jobs,
            vectors=store,
            embedder=embed,
            knowledge=knowledge,
        ),
        knowledge=knowledge,
        storage=storage,
        state=state,
        jobs=jobs,
        vectors=store,
        embedder=embed,
    )
