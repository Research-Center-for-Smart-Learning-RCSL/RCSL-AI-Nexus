"""Stable explicit compatibility facade."""

from .base import (
    router,
)
from .collections import (
    create_collection,
    delete_collection,
    list_collections,
)
from .documents import (
    delete_document,
    list_documents,
    read_document,
    read_document_text,
    read_ingestion_job,
    reindex_document,
    upload_document,
)
from .search import (
    search_knowledge,
)

__all__ = [
    "router",
    "list_collections",
    "create_collection",
    "delete_collection",
    "list_documents",
    "read_document",
    "upload_document",
    "read_document_text",
    "reindex_document",
    "read_ingestion_job",
    "delete_document",
    "search_knowledge",
]
