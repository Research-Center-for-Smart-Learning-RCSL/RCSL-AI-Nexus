"""The Qdrant adapter, against a stubbed transport.

No Qdrant in the loop: what is worth pinning here is the shape of the requests,
because that shape is where the tenant boundary lives. Every call must name a
collection derived from the tenant and carry a tenant condition in its filter,
and neither can come from an argument.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.vector.qdrant_store import COLLECTION_PREFIX, QdrantVectorStore, point_id
from app.domain.entities.knowledge import DocumentChunk
from app.domain.exceptions import VectorStoreError

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "99999999-9999-9999-9999-999999999999"
DOCUMENT = "22222222-2222-2222-2222-222222222222"


class Recorder:
    """Captures each request and answers with a canned response."""

    def __init__(self, responses: dict[str, httpx.Response] | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self._responses = responses or {}

    async def __call__(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        self.calls.append((method, path, kwargs.get("json"), kwargs.get("params")))
        return self._responses.get(path, httpx.Response(200, json={"result": []}))

    def bodies_for(self, path_fragment: str) -> list[dict]:
        return [c[2] for c in self.calls if path_fragment in c[1] and c[2] is not None]


@pytest.fixture
def recorder(monkeypatch) -> Recorder:
    rec = Recorder()

    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        return await rec(method, path, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    return rec


def store(tenant: str = TENANT_A) -> QdrantVectorStore:
    return QdrantVectorStore("http://qdrant:6333", "a-key", tenant)


def chunk(index: int = 0, text: str = "a passage") -> DocumentChunk:
    return DocumentChunk(
        document_id=DOCUMENT,
        collection_id="col-1",
        index=index,
        text=text,
        vector=[0.1, 0.2, 0.3],
    )


# --- the tenant boundary -------------------------------------------------


def test_the_collection_name_comes_from_the_tenant() -> None:
    """A per-tenant collection is what makes a lost tenant fail closed: the
    request names a collection that does not exist rather than reading every
    tenant's passages, which a missing payload filter would do."""
    assert store(TENANT_A)._collection == f"{COLLECTION_PREFIX}{TENANT_A}"
    assert store(TENANT_A)._collection != store(TENANT_B)._collection


def test_a_tenant_id_that_is_not_a_uuid_is_refused_at_construction() -> None:
    """The collection name is interpolated from it, so it may not be arbitrary."""
    with pytest.raises(ValueError, match="uuid"):
        QdrantVectorStore("http://qdrant:6333", "a-key", "../escape")


async def test_every_request_targets_only_this_tenants_collection(recorder: Recorder) -> None:
    subject = store(TENANT_A)
    await subject.upsert([chunk()])
    await subject.delete_document(DOCUMENT)
    await subject.search([0.1], limit=3)

    assert recorder.calls
    for _, path, _, _ in recorder.calls:
        assert f"{COLLECTION_PREFIX}{TENANT_A}" in path
        assert TENANT_B not in path


async def test_search_and_delete_carry_a_tenant_condition_in_the_filter(
    recorder: Recorder,
) -> None:
    """The second layer. It is not a parameter, so no caller can issue a search
    without it; security.md 7.3."""
    subject = store(TENANT_A)
    await subject.search([0.1], limit=3)
    await subject.delete_document(DOCUMENT)

    for body in recorder.bodies_for("/points"):
        conditions = body["filter"]["must"]
        assert {"key": "tenant_id", "match": {"value": TENANT_A}} in conditions


async def test_a_collection_filter_narrows_but_never_replaces_the_tenant_one(
    recorder: Recorder,
) -> None:
    await store(TENANT_A).search([0.1], limit=3, collection_id="col-1")

    conditions = recorder.bodies_for("/points/search")[0]["filter"]["must"]
    keys = [c["key"] for c in conditions]
    assert "tenant_id" in keys
    assert "collection_id" in keys


async def test_the_stored_payload_records_the_tenant(recorder: Recorder) -> None:
    await store(TENANT_A).upsert([chunk()])
    payload = recorder.bodies_for("/points")[0]["points"][0]["payload"]
    assert payload["tenant_id"] == TENANT_A


# --- idempotence ---------------------------------------------------------


def test_point_ids_are_derived_so_re_indexing_overwrites() -> None:
    """Generated ids would accumulate a second copy of every passage on a
    re-index, and both copies would then be retrieved."""
    assert point_id(DOCUMENT, 0) == point_id(DOCUMENT, 0)
    assert point_id(DOCUMENT, 0) != point_id(DOCUMENT, 1)
    assert point_id(DOCUMENT, 0) != point_id("33333333-2222-2222-2222-222222222222", 0)


async def test_upsert_with_no_chunks_makes_no_request(recorder: Recorder) -> None:
    await store().upsert([])
    assert recorder.calls == []


# --- lifecycle -----------------------------------------------------------


async def test_ensure_ready_leaves_an_existing_collection_alone(monkeypatch) -> None:
    """Recreating it would silently invalidate every stored passage, so a
    changed embedding model has to be a deliberate re-index."""
    rec = Recorder()

    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        await rec(method, path, **kwargs)
        return httpx.Response(200, json={"result": {"status": "green"}})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    await store().ensure_ready(768)

    assert [c[0] for c in rec.calls] == ["GET"]


async def test_ensure_ready_creates_the_collection_and_its_payload_indexes(
    monkeypatch,
) -> None:
    rec = Recorder()

    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        await rec(method, path, **kwargs)
        if method == "GET":
            return httpx.Response(404, json={"status": {"error": "not found"}})
        return httpx.Response(200, json={"result": True})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    await store().ensure_ready(768)

    creates = [c for c in rec.calls if c[0] == "PUT" and c[1].endswith(store()._collection)]
    assert creates[0][2] == {"vectors": {"size": 768, "distance": "Cosine"}}
    # Without these the tenant and collection conditions scan rather than seek.
    indexed = [c[2]["field_name"] for c in rec.calls if c[1].endswith("/index")]
    assert indexed == ["tenant_id", "collection_id"]


# --- failure behaviour ---------------------------------------------------


async def test_searching_before_anything_is_indexed_returns_nothing(monkeypatch) -> None:
    """A tenant that has indexed nothing has no collection. An empty result lets
    retrieval proceed without the knowledge base; raising would fail a chat that
    had nothing to do with it."""

    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(404, json={"status": {"error": "not found"}})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    assert await store().search([0.1], limit=3) == []


async def test_a_qdrant_error_becomes_a_domain_error(monkeypatch) -> None:
    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(500, text="internal")

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(VectorStoreError):
        await store().upsert([chunk()])


async def test_an_unreachable_qdrant_becomes_a_domain_error(monkeypatch) -> None:
    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(VectorStoreError):
        await store().search([0.1], limit=3)


async def test_a_point_with_no_text_is_skipped_rather_than_passed_on(monkeypatch) -> None:
    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": [
                    {"score": 0.9, "payload": {"document_id": DOCUMENT}},
                    {
                        "score": 0.8,
                        "payload": {
                            "document_id": DOCUMENT,
                            "collection_id": "col-1",
                            "index": 2,
                            "text": "a real passage",
                        },
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    passages = await store().search([0.1], limit=5)

    assert [p.text for p in passages] == ["a real passage"]
    assert passages[0].index == 2


async def test_the_api_key_is_sent_on_every_request(monkeypatch) -> None:
    """Qdrant ships with no authentication at all (security.md 10)."""
    seen: list[str | None] = []

    async def request(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        headers = kwargs.get("headers") or {}
        seen.append(headers.get("api-key"))  # type: ignore[union-attr]
        return httpx.Response(200, json={"result": []})

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    subject = store()
    await subject.upsert([chunk()])
    await subject.search([0.1], limit=1)

    assert seen == ["a-key", "a-key"]
