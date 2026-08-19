"""Stable explicit compatibility facade."""

from .details import (
    error_response,
    public_details,
)
from .handlers import (
    install_error_handlers,
)
from .mapping import (
    STATUS_MAP,
    _status_for,
)

__all__ = [
    "STATUS_MAP",
    "_status_for",
    "error_response",
    "public_details",
    "install_error_handlers",
]
