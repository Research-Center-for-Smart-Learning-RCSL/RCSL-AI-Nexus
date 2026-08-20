"""Stable explicit compatibility facade."""

from .prompt import (
    _SURFACE_HELP,
    ASSIST_CAPABILITY,
    build_system_prompt,
)
from .streaming import (
    AssistOperator,
)

__all__ = [
    "ASSIST_CAPABILITY",
    "AssistOperator",
    "_SURFACE_HELP",
    "build_system_prompt",
]
