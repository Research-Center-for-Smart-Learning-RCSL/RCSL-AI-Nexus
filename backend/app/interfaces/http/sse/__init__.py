"""Stable explicit compatibility facade."""

from .encoding import (
    CAPABILITY_DEFAULTED_HEADER,
    CITATION_HEADER,
    DONE_SENTINEL,
    STREAM_HEADERS,
    Trailer,
    capability_defaulted_header,
    citation_header,
    created_now,
    frame,
    new_completion_id,
)
from .frames import (
    _frames,
)
from .response import (
    prime,
    streaming_response,
)

__all__ = [
    "DONE_SENTINEL",
    "STREAM_HEADERS",
    "frame",
    "new_completion_id",
    "prime",
    "Trailer",
    "streaming_response",
    "CITATION_HEADER",
    "citation_header",
    "CAPABILITY_DEFAULTED_HEADER",
    "capability_defaulted_header",
    "created_now",
    "_frames",
]
