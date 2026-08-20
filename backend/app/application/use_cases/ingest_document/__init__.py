"""Stable explicit compatibility facade."""

from .facade import (
    IngestDocument,
)
from .state import (
    INGESTABLE_STATES,
    REINDEXABLE_STATES,
    DocumentStateCommitterPort,
)

__all__ = [
    "DocumentStateCommitterPort",
    "INGESTABLE_STATES",
    "IngestDocument",
    "REINDEXABLE_STATES",
]
