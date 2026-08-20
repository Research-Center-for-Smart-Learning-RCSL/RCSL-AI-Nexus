"""Flat knowledge setting declarations."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class KnowledgeSettings(BaseSettings):
    document_storage_path: str = "/var/lib/nexus/documents"
    """Where uploaded documents and their extracted text are kept.

    A mounted volume rather than MinIO, decided when the knowledge base was
    built: one node, one filesystem, and MinIO would have added a service, a set
    of default credentials to replace, and a CVE surface for features this
    deployment does not use. See ARCHITECTURE.md section 6 and
    adapters/storage/filesystem_documents.py.
    """

    parser_base_url: str = "http://parser:8000"
    """The isolated document parser (app/parser/main.py). A sibling container on
    an internal network, unlike the runtimes, which are on the host: this one
    must reach nothing, so it is deliberately not on `host.docker.internal`."""

    parser_timeout_seconds: int = 120

    qdrant_base_url: str = "http://qdrant:6333"

    qdrant_timeout_seconds: int = 30
    """The passage index. Reached over its REST API rather than through
    `qdrant-client`, which would pull grpcio and protobuf into an image that
    needs neither; see adapters/vector/qdrant_store.py."""
