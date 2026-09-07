"""The memory budget's arithmetic, and which figure it charges a model at.

Two numbers describe a resident model and they count different things. The
declared profile is registered by hand and, since the 2026-08-14 correction,
is meant to include the KV cache the registered `context_length` buys.
`observed_memory_gb` is what the runtime reports — Ollama's `size_vram`, which
was measured at 31.58 GiB for `gemma4-31b-q8` at `num_ctx` 131072, 196608 and
262144 alike, against a resident `llama-server` of 37.34, 40.40 and 42.93 GiB.
It is the weights, and it under-counts by the cache.

So the budget takes the **larger** of the two: the profile as the estimate of
resident cost, the observation as a floor under a profile registered too low.
It read them the other way round until 2026-09-07, which charged the target its
declared figure while crediting the residents their weights alone — two sides
of one subtraction in different units, and the reason `gemma4-31b-q8` became
unloadable when `NODE_TOTAL_MEMORY_GB` was sized against the observed figures.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import InsufficientMemoryError
from app.domain.services.memory_budget_service import MemoryBudgetService
from app.infrastructure.config.runtime import RuntimeSettings


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


def test_an_observation_above_the_profile_outranks_it() -> None:
    """Budget 8 GB (10 × 0.8). Declared in-use 4.0 leaves room for 3.0;
    observed in-use 5.5 does not. A model demonstrably holding more than it
    declared is counted at what it holds."""
    budget = MemoryBudgetService()
    resident = _model("resident", declared_gb=4.0, observed_gb=5.5)
    target = _model("incoming", declared_gb=3.0)

    with pytest.raises(InsufficientMemoryError):
        budget.assert_can_load(target, _node(10.0), [resident])


def test_an_observation_below_the_profile_does_not_discount_it() -> None:
    """The other direction, and the one that broke `code` on 2026-09-07.

    Budget 8 GB. The resident declares 4.0 and the runtime reports 1.0, because
    `size_vram` is the weights and the profile is the weights plus the KV cache
    the registered context buys. Charging the observation would leave room for
    a 5.0 target that does not fit.
    """
    budget = MemoryBudgetService()
    resident = _model("resident", declared_gb=4.0, observed_gb=1.0)
    target = _model("incoming", declared_gb=5.0)

    with pytest.raises(InsufficientMemoryError):
        budget.assert_can_load(target, _node(10.0), [resident])


def test_declared_profile_still_counts_where_nothing_was_observed() -> None:
    budget = MemoryBudgetService()
    resident = _model("resident", declared_gb=4.0)
    target = _model("incoming", declared_gb=3.0)

    budget.assert_can_load(target, _node(10.0), [resident])

    with pytest.raises(InsufficientMemoryError):
        budget.assert_can_load(replace(target, id="x"), _node(8.0), [resident])


def test_the_deployments_own_shape_at_its_configured_fraction() -> None:
    """The live arrangement, pinned as arithmetic so a settings change that
    would strand a capability fails here rather than in the admin UI.

    64 GiB x 0.80 = 51.2 against 51 registered for the three models this host
    keeps resident. The profiles are what llama.cpp reports allocating: 44.02
    GiB for `gemma4-31b-q8` at 262144, 5.32 for `qwen2.5:7b` at 32768, 0.30 for
    the embedder at 2048.
    """
    budget = MemoryBudgetService(headroom_fraction=0.80)
    node = _node(64.0)
    small = [
        _model("qwen7b", declared_gb=6.0, observed_gb=5.32),
        _model("embedder", declared_gb=1.0, observed_gb=0.34461914002895355),
    ]
    incumbent = _model("gemma4-31b-q8", declared_gb=44.0)

    # All three together, which is the arrangement the deployment exists in.
    budget.assert_can_load(incumbent, node, small)

    # And nothing else, on 0.2 GiB of margin.
    with pytest.raises(InsufficientMemoryError):
        budget.assert_can_load(_model("glm47-flash", declared_gb=32.0), node, [*small, incumbent])


def test_a_smaller_headroom_would_strand_the_capability_that_has_one_candidate() -> None:
    """0.70 was this deployment's setting for an hour on 2026-09-07, sized
    against a 9.4 GiB VM footprint before the VM was capped at 3 GiB.

    It is kept as a test rather than a comment because the failure it produced
    is invisible from the settings file: `code` has one candidate, the budget
    refuses it, and the capability is simply gone.
    """
    node = _node(64.0)
    small = [
        _model("qwen7b", declared_gb=6.0, observed_gb=5.32),
        _model("embedder", declared_gb=1.0, observed_gb=0.34461914002895355),
    ]

    with pytest.raises(InsufficientMemoryError):
        MemoryBudgetService(headroom_fraction=0.70).assert_can_load(
            _model("gemma4-31b-q8", declared_gb=44.0), node, small
        )


def test_the_shipped_defaults_are_the_deployment_s_own_figures() -> None:
    """Both halves of the product, read off the field declarations.

    `RuntimeSettings.model_fields` rather than `RuntimeSettings()`: the latter
    reads `os.environ`, so on any shell that exports either variable this would
    assert the ambient value and pass or fail for reasons having nothing to do
    with the code. What is pinned here is what ships when nothing overrides.

    **It cannot see `.env`, which is where the deployment's real values live and
    is not in the repository.** The regression it does catch is a default
    drifting away from the host it was measured on; `.env` drifting is caught by
    `admin_api_end_to_end_fixtures`, which pins both, and by nothing else.

    0.80 is also the domain default, so this asserts a coincidence — and the
    coincidence is the point: the fraction came back to the default because the
    Colima VM was capped at 3 GiB, not because nothing was ever wrong with it.
    """
    fields = RuntimeSettings.model_fields

    assert fields["node_total_memory_gb"].default == 64.0
    assert fields["node_memory_headroom_fraction"].default == 0.80
