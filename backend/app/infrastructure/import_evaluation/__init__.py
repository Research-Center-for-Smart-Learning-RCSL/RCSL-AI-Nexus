"""Stable explicit compatibility facade."""

from .cli import (
    main,
)
from .parsing import (
    parse_samples,
)
from .service import (
    run,
)

__all__ = [
    "main",
    "parse_samples",
    "run",
]
