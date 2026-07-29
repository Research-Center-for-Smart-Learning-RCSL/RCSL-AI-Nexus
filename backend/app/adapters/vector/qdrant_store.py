"""Qdrant, over its REST API.

**No `qdrant-client`, deliberately.** The client pulls grpcio and protobuf into
an image that needs neither, which is a large addition to the supply-chain
surface section 10 asks to keep small, for a few HTTP calls this file makes in
a hundred lines. The runtime adapters and the parser client already talk plain
httpx; this is the same choice for the same reason.

**The tenant boundary is enforced twice, and the first one fails closed.** Each
tenant gets its own Qdrant collection, named from the tenant this adapter was
constructed with, so a search that somehow lost its tenant asks for a collection
that does not exist and gets an error rather than every tenant's passages. The
payload filter security.md section 7.3 describes is applied as well, which
covers the case of two tenants ever sharing a collection. A single shared
collection with only the filter was the documented design; the deviation is
recorded there, and the reason is that a missing filter fails open while a
missing collection name fails closed.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from typing import Any

import httpx

from app.domain.entities.knowledge import DocumentChunk, RetrievedPassage
from app.domain.exceptions import VectorStoreError

logger = logging.getLogger(__name__)

COLLECTION_PREFIX = "kb_"
_TENANT = re.compile(r"\A[0-9a-fA-F-]{36}\Z")

_POINT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")
"""Fixed namespace for deriving a point id from (document, passage index).

Qdrant accepts a UUID or an unsigned integer as a point id, and deriving it
rather than generating one is what makes re-indexing idempotent: the same
passage of the same document lands on the same id and overwrites, instead of
accumulating a second copy that would then be retrieved twice.
"""


def point_id(document_id: str, index: int) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{document_id}:{index}"))


class QdrantVectorStore:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        tenant_id: str,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        if not _TENANT.match(tenant_id):
            raise ValueError(f"tenant id is not a uuid: {tenant_id!r}")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._tenant_id = tenant_id
        self._collection = f"{COLLECTION_PREFIX}{tenant_id}"
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(timeout_seconds), write=30.0, pool=5.0
        )

    # --- lifecycle -------------------------------------------------------

    async def ensure_ready(self, vector_size: int) -> None:
        """Create the collection if absent, sized for the embedding model.

        Cosine distance, because embedding models are trained for it and the
        vectors are not normalised here. A collection that already exists is
        left alone: changing the vector size would silently invalidate every
        stored passage, so a changed embedding model has to be a deliberate
        re-index rather than something this quietly does.
        """
        existing = await self._request("GET", f"/collections/{self._collection}", allow=(404,))
        if existing.status_code == 200:
            return
        await self._request(
            "PUT",
            f"/collections/{self._collection}",
            json={"vectors": {"size": vector_size, "distance": "Cosine"}},
        )
        # Payload indexes on the two fields every filter uses. Without them
        # Qdrant still filters correctly but scans, which turns the tenant and
        # collection conditions into a cost that grows with the whole index.
        for field in ("tenant_id", "collection_id"):
            await self._request(
                "PUT",
                f"/collections/{self._collection}/index",
                json={"field_name": field, "field_schema": "keyword"},
            )

    # --- writes ----------------------------------------------------------

    async def upsert(self, chunks: Sequence[DocumentChunk]) -> None:
        if not chunks:
            return
        points = [
            {
                "id": point_id(chunk.document_id, chunk.index),
                "vector": chunk.vector,
                "payload": {
                    # Stored even though the collection is already per-tenant:
                    # it is what the second filter matches on, and it makes a
                    # point self-describing if collections are ever merged.
                    "tenant_id": self._tenant_id,
                    "document_id": chunk.document_id,
                    "collection_id": chunk.collection_id,
                    "index": chunk.index,
                    "text": chunk.text,
                },
            }
            for chunk in chunks
        ]
        await self._request(
            "PUT",
            f"/collections/{self._collection}/points",
            params={"wait": "true"},
            json={"points": points},
        )

    async def delete_document(self, document_id: str) -> None:
        """By filter rather than by listing ids, so it removes every passage
        including ones a shorter re-index left behind. 404 is success: a
        document whose passages were never indexed must still be deletable."""
        await self._request(
            "POST",
            f"/collections/{self._collection}/points/delete",
            params={"wait": "true"},
            json={"filter": self._filter(document_id=document_id)},
            allow=(404,),
        )

    # --- reads -----------------------------------------------------------

    async def search(
        self, vector: Sequence[float], *, limit: int, collection_id: str | None = None
    ) -> list[RetrievedPassage]:
        response = await self._request(
            "POST",
            f"/collections/{self._collection}/points/search",
            json={
                "vector": list(vector),
                "limit": limit,
                "filter": self._filter(collection_id=collection_id),
                "with_payload": True,
            },
            allow=(404,),
        )
        if response.status_code == 404:
            # No collection yet means this tenant has indexed nothing. An empty
            # result is the honest answer and lets retrieval proceed without
            # the knowledge base; raising would make an unrelated chat fail.
            return []

        found = response.json().get("result") or []
        passages: list[RetrievedPassage] = []
        for hit in found:
            payload = hit.get("payload") or {}
            text = payload.get("text")
            if not isinstance(text, str):
                # A point without text is unusable and, more to the point, not
                # something this should pass on as a passage.
                logger.warning("qdrant returned a point with no text payload")
                continue
            passages.append(
                RetrievedPassage(
                    document_id=str(payload.get("document_id", "")),
                    collection_id=str(payload.get("collection_id", "")),
                    index=int(payload.get("index", 0)),
                    text=text,
                    score=float(hit.get("score", 0.0)),
                )
            )
        return passages

    # --- internals -------------------------------------------------------

    def _filter(
        self, *, document_id: str | None = None, collection_id: str | None = None
    ) -> dict[str, Any]:
        """The tenant condition is unconditional and comes from the constructor.

        It is never a parameter, so no caller can issue a search without it;
        that is the whole of section 7.3 expressed in this adapter.
        """
        must: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": self._tenant_id}}]
        if document_id is not None:
            must.append({"key": "document_id", "match": {"value": document_id}})
        if collection_id is not None:
            must.append({"key": "collection_id", "match": {"value": collection_id}})
        return {"must": must}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        allow: tuple[int, ...] = (),
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    # Qdrant has no authentication at all by default
                    # (security.md section 10). This is the key set through
                    # QDRANT__SERVICE__API_KEY from a file secret.
                    headers={"api-key": self._api_key},
                )
        except httpx.HTTPError as exc:
            raise VectorStoreError(detail=f"qdrant {method} {path}: {exc}") from exc

        if response.status_code >= 400 and response.status_code not in allow:
            # The body goes to the log, not to the caller: it can echo the
            # request, and a request here carries passage text.
            logger.warning(
                "qdrant_error method=%s path=%s status=%s body=%s",
                method,
                path,
                response.status_code,
                response.text[:500],
            )
            raise VectorStoreError(detail=f"qdrant {method} {path} returned {response.status_code}")
        return response
