"""Refuses model loads that would exceed a node's memory budget.

Phase 1 uses static capacity from the database rather than live metrics:
`MetricsPort` arrives in Phase 2 and this check must not wait for it. On
unified memory hardware an over-commit does not fail cleanly, it drives the
machine into swap, so the check is a refusal rather than a warning.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.entities.model import Model
from app.domain.entities.node import Node
from app.domain.exceptions import InsufficientMemoryError

DEFAULT_HEADROOM_FRACTION = 0.8
"""Leave a fifth of the machine for the OS, the containers, and inference
working memory that is not counted in a model's resource profile."""


class MemoryBudgetService:
    def __init__(self, headroom_fraction: float = DEFAULT_HEADROOM_FRACTION) -> None:
        self._headroom = headroom_fraction

    def assert_can_load(self, target: Model, node: Node, already_loaded: Iterable[Model]) -> None:
        budget = node.total_memory_gb * self._headroom
        in_use = sum(m.resource_profile.memory_gb for m in already_loaded if m.id != target.id)
        available = budget - in_use
        required = target.resource_profile.memory_gb

        if required > available:
            raise InsufficientMemoryError(required_gb=required, available_gb=max(available, 0.0))
