"""The memory budget's arithmetic, now that observed figures exist.

The declared profile is whatever a person typed into a form; the observed
figure is what the runtime reports actually holding, KV cache included. The
gap is real — 5.7 GB measured against 4.7 GB of declared weights for a 7B
model — and the budget refusing on the honest number is the whole point of
reading it back.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import InsufficientMemoryError
from app.domain.services.memory_budget_service import MemoryBudgetService


def _model(alias: str, declared_gb: float, observed_gb: float | None = None) -> Model:
    return Model(
        id=f"id-{alias}",
        alias=alias,
        ref=alias,
        runtime=RuntimeKind.OLLAMA,
        node_id="n1",
        state=ModelState.LOADED,
        capabilities=frozenset({"chat"}),
        resource_profile=ResourceProfile(memory_gb=declared_gb, context_length=8192),
        observed_state=ModelState.LOADED if observed_gb is not None else None,
        observed_memory_gb=observed_gb,
    )


def _node(total_gb: float) -> Node:
    return Node(
        id="n1",
        name="n1",
        address="100.64.0.1",
        status=NodeStatus.ONLINE,
        total_memory_gb=total_gb,
    )


def test_observed_figure_outranks_the_declared_profile() -> None:
    """Budget 8 GB (10 × 0.8). Declared in-use 4.0 leaves room for 3.0;
    observed in-use 5.5 does not. The refusal must follow the observation."""
    budget = MemoryBudgetService()
    resident = _model("resident", declared_gb=4.0, observed_gb=5.5)
    target = _model("incoming", declared_gb=3.0)

    with pytest.raises(InsufficientMemoryError):
        budget.assert_can_load(target, _node(10.0), [resident])


def test_declared_profile_still_counts_where_nothing_was_observed() -> None:
    budget = MemoryBudgetService()
    resident = _model("resident", declared_gb=4.0)
    target = _model("incoming", declared_gb=3.0)

    budget.assert_can_load(target, _node(10.0), [resident])

    with pytest.raises(InsufficientMemoryError):
        budget.assert_can_load(replace(target, id="x"), _node(8.0), [resident])
