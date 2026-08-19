"""Knowledge domain errors."""

from __future__ import annotations

from .base import DomainError, StateConflictError


class CollectionStateConflictError(StateConflictError):
    code = "collection_state_conflict"
    public_message = "That change to the collection is not allowed."


class CollectionNotFoundError(DomainError):
    code = "collection_not_found"
    public_message = "That collection does not exist."


class DocumentNotFoundError(DomainError):
    code = "document_not_found"
    public_message = "That document does not exist."


class UploadRejectedError(DomainError):
    code = "upload_rejected"
    public_message = "This file cannot be accepted."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail)
        self.public_detail = detail
        """Unlike most errors here, the reason is safe to show: it describes the
        caller's own file (too large, wrong type) and reveals nothing about the
        platform. The router decides whether to include it."""


class DocumentParseError(DomainError):
    code = "document_parse_failed"
    public_message = "The document could not be read."


class VectorStoreError(DomainError):
    code = "vector_store_unavailable"
    public_message = "The knowledge index is not available."


class DocumentStateConflictError(DomainError):
    code = "document_state_conflict"
    public_message = "The document is not in a state that allows this operation."
