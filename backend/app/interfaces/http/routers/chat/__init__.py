"""Stable explicit compatibility facade."""

from .collection import (
    _collect,
)
from .route import (
    chat_completions,
    list_models,
    router,
)
from .translation import (
    _flatten,
    _sampling,
    _to_domain,
    _tool_choice,
    _tools,
)

__all__ = [
    "_flatten",
    "_to_domain",
    "_tools",
    "_tool_choice",
    "_sampling",
    "_collect",
    "router",
    "list_models",
    "chat_completions",
]
