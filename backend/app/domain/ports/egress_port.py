"""Guarding outbound requests the platform makes on a caller's behalf.

A node address is validated through this port rather than by importing the guard
into the use case directly, for the same reason model-reference validation goes
through `ModelRuntimePort`: the application layer stays free of adapter imports,
and the check (which resolves DNS) is I/O that belongs behind a port. See
adapters/http/egress_guard.py and security.md section 7.2.
"""

from __future__ import annotations

from typing import Protocol


class EgressGuardPort(Protocol):
    async def assert_node_address_allowed(self, address: str) -> None:
        """Raise `InvalidNodeAddressError` unless the address is a safe tailnet
        target. Called before a node address is stored, because a stored address
        is one the platform will later make outbound requests to."""
        ...
