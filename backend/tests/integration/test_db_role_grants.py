"""The database account split, enforced by a real Postgres (security.md §6).

`tests/unit/test_db_roles.py` pins that the generated SQL says the gateway may
write only `usage_records`. This test proves the server enforces it: with the
grants applied, the gateway account is refused an INSERT into `api_keys`,
`users`, `routing_policies` and `audit_log`, while keeping SELECT on them and
INSERT on `usage_records`. That boundary is the whole point of the split and
cannot be checked without a live server, so it is the one property most worth
exercising before the first deploy.

Skipped unless `TEST_DATABASE_URL` is set. The account it names must be able to
CREATE ROLE (the postgres image's default superuser is), because the test
provisions the two roles the way `migrate` does in production.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.db_roles import RoleSpec, apply_statements, build_statements

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

# Suffixed so a run against a shared cluster cannot collide with a real
# deployment's `nexus_gateway` / `nexus_admin`.
GATEWAY = RoleSpec(name="nexus_gateway_test", password="gw-secret", profile="gateway")
ADMIN = RoleSpec(name="nexus_admin_test", password="admin-secret", profile="admin")


def _url_for(owner_url: str, spec: RoleSpec):
    return make_url(owner_url).set(username=spec.name, password=spec.password)


async def _denied(engine, sql: str, **params) -> None:
    async with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as excinfo:
            await conn.execute(text(sql), params)
    assert "permission denied" in str(excinfo.value).lower()


async def _allowed(engine, sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def _drop_roles(owner_url: str) -> None:
    engine = create_async_engine(owner_url)
    try:
        for name in (GATEWAY.name, ADMIN.name):
            # Best effort: a role absent because the test failed early is fine.
            with contextlib.suppress(Exception):
                async with engine.begin() as conn:
                    # DROP OWNED BY first: it removes the role's grants and
                    # default-privilege entries, which otherwise block DROP ROLE.
                    await conn.exec_driver_sql(f'DROP OWNED BY "{name}"')
                    await conn.exec_driver_sql(f'DROP ROLE "{name}"')
    finally:
        await engine.dispose()


async def test_gateway_account_is_denied_writes_outside_usage_records(database_url) -> None:
    # The fixture has already rebuilt the schema through Alembic, as the owner.
    owner_url = database_url
    statements = build_statements([GATEWAY, ADMIN], database=make_url(owner_url).database)
    await apply_statements(owner_url, statements)

    gateway = create_async_engine(_url_for(owner_url, GATEWAY))
    admin = create_async_engine(_url_for(owner_url, ADMIN))
    try:
        # Reads the gateway legitimately needs: it verifies API keys and reads
        # routing policies to serve a request.
        async with gateway.connect() as conn:
            await conn.execute(text("SELECT 1 FROM api_keys LIMIT 1"))
            await conn.execute(text("SELECT 1 FROM routing_policies LIMIT 1"))

        # The one write it must have. `tenant_id` is supplied because the
        # multi-tenancy migration made it NOT NULL on this table; the row only
        # has to be valid, so it uses the tenant that migration seeds. Without
        # it the INSERT fails on the constraint before reaching the grant, and
        # every denial below goes unasserted.
        await _allowed(
            gateway,
            "INSERT INTO usage_records "
            "(id, actor_id, tenant_id, capability, model_alias, tokens, latency_ms, "
            "completed, at) "
            "VALUES (:id, :actor, 'default', 'chat', 'm', 1, 1, true, :at)",
            id=str(uuid.uuid4()),
            actor=str(uuid.uuid4()),
            at=datetime.now(UTC),
        )

        # The writes it must be refused. Minting a key or a user is the attack
        # the split exists to stop; forging an audit row would hide it.
        await _denied(gateway, "INSERT INTO api_keys (id) VALUES (:id)", id=str(uuid.uuid4()))
        await _denied(gateway, "UPDATE api_keys SET name = 'x'")
        await _denied(gateway, "DELETE FROM api_keys")
        await _denied(gateway, "INSERT INTO users (id) VALUES (:id)", id=str(uuid.uuid4()))
        await _denied(
            gateway, "INSERT INTO routing_policies (capability) VALUES ('chat')"
        )
        await _denied(gateway, "INSERT INTO audit_log (id) VALUES (:id)", id=str(uuid.uuid4()))

        # Positive control: the admin account has the write the gateway lacks,
        # so the denials above are the grant working, not the table being
        # unwritable.
        await _allowed(
            admin,
            "INSERT INTO users (id, login, tenant_id, display_name, role) "
            "VALUES (:id, :login, 'default', 'Test', 'admin')",
            id=str(uuid.uuid4()),
            login=f"{uuid.uuid4()}@example.com",
        )
    finally:
        await gateway.dispose()
        await admin.dispose()
        await _drop_roles(owner_url)
