"""Tenant: the isolation boundary for users, keys, usage, and (later) the
knowledge base.

Phase 1 was single tenant and said so. The isolation boundary is now real: every
`users`, `api_keys`, `usage_records` and `audit_log` row carries a `tenant_id`,
and the tenant-scoped repositories filter every read and stamp every write by it,
inside the adapter, so a use case cannot forget it (security.md section 7.3).

Shared infrastructure stays platform-global on purpose: `models`, `nodes`, and
`routing_policies` are the compute the tenants share, so they carry no tenant_id.

`DEFAULT_TENANT_ID` is the tenant every pre-existing row was backfilled into and
the one a fresh deployment bootstraps its first admin into. It is a stable
well-known id rather than a generated one so the migration and the entity
defaults agree without a lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

DEFAULT_TENANT_ID = "default"
DEFAULT_TENANT_NAME = "Default"


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str
    created_at: datetime | None = None
    """Assigned by the database on first write; `None` means "not persisted
    yet", matching the other entities."""
