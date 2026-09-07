"""Refuses model loads that would exceed a node's memory budget.

Phase 1 uses static capacity from the database rather than live metrics:
`MetricsPort` arrives in Phase 2 and this check must not wait for it. On
unified memory hardware an over-commit does not fail cleanly, it drives the
machine into swap, so the check is a refusal rather than a warning.

**Both sides of the subtraction must be the same kind of number**, and until
2026-09-07 they were not: the target was charged its declared profile while the
residents were credited at whatever the runtime reported, and those two figures
count different things. See `assert_can_load`.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.entities.model import Model
from app.domain.entities.node import Node
from app.domain.exceptions import InsufficientMemoryError

DEFAULT_HEADROOM_FRACTION = 0.8
"""What a node keeps back from `total_memory_gb` for the OS, the containers,
and inference working memory that is not counted in a model's resource profile.

**A host whose containers sit under a hypervisor has to reserve that VM too,
and the right response is usually to make the VM smaller rather than this
number.** The Mac Studio is the worked example: its Colima VM was allocated 6
GiB and its *host* footprint reached 9.4, because the footprint is the
allocation plus the guest page cache that grows to fill it. Lowering this
fraction to cover that stranded `gemma4-31b-q8`, the only candidate the `code`
capability has, while the eleven containers were using 1.3 GiB of the 6.
Capping the VM at 3 GiB put the deployment back on this default.

No fraction is right for every host, which is why `NODE_MEMORY_HEADROOM_FRACTION`
exists; but a fraction that refuses a model the host could hold is the more
expensive way to be wrong, and it is the direction a hypervisor tempts you in.
"""


class MemoryBudgetService:
    def __init__(self, headroom_fraction: float = DEFAULT_HEADROOM_FRACTION) -> None:
        self._headroom = headroom_fraction

    def assert_can_load(self, target: Model, node: Node, already_loaded: Iterable[Model]) -> None:
        """Refuse `target` when it would not fit beside what is already resident.

        **The declared profile is the estimate of resident cost and the observed
        figure is a floor under it, not a replacement for it.** This is the
        reverse of what the code did until 2026-09-07, and the comment that
        justified it — that the runtime's figure "includes the KV cache the
        profile does not" — was measured false on 2026-08-14: Ollama reports
        `size_vram` 31.58 GiB for `gemma4-31b-q8` at `num_ctx` 131072, 196608
        *and* 262144, while `llama-server`'s resident size over the same three
        is 37.34, 40.40 and 42.93 GiB. `observed_memory_gb` is the weights; it
        under-counts by the whole KV cache, and that cache is what a registered
        `context_length` buys. The profiles were corrected to include it —
        `gemma4-31b-q8` to 41 GiB then, and to **44** on 2026-09-07 when
        `common_memory_breakdown_print` was read instead of estimated (30.38
        model + 11.25 context + 2.40 compute) — so the declared figure is now
        the honest one, and taking the observation over it charges a resident
        model for its weights alone.

        The observation is still a floor, because a profile can be registered
        too low by hand and a model that is demonstrably holding more than it
        declared must be counted at what it holds. Taking the larger keeps the
        error on the side of a refusal, which is the safe direction here: a
        wrong refusal costs an operator a configuration change, and a wrong
        admission costs the whole host.

        **What this cost.** `NODE_TOTAL_MEMORY_GB` was lowered to 54 on
        2026-09-07 against a floor computed from the observed figures (39.05
        GiB for the three resident models), while this method charged the
        target its declared 41 — so `gemma4-31b-q8` became unloadable and
        `code`, whose only candidate it is, had no target at all. The mismatch
        was invisible while the model stayed resident, because `load()` returns
        early on an already-loaded model without reaching this check.
        """
        budget = node.total_memory_gb * self._headroom
        in_use = sum(
            max(m.resource_profile.memory_gb, m.observed_memory_gb or 0.0)
            for m in already_loaded
            if m.id != target.id
        )
        available = budget - in_use
        required = target.resource_profile.memory_gb

        if required > available:
            raise InsufficientMemoryError(required_gb=required, available_gb=max(available, 0.0))
