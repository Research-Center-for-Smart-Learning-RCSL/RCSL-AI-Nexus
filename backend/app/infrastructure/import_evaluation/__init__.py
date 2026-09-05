"""Stable explicit compatibility facade."""

from .cli import (
    main,
)
from .parsing import (
    parse_samples,
    parse_task_definitions,
)
from .service import (
    run,
)

__all__ = [
    "main",
    "parse_samples",
    "parse_task_definitions",
    "run",
]
