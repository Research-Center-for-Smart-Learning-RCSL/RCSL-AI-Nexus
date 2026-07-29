"""The database role split (security.md section 6).

The property under test is a security boundary: the gateway account may read
every table but may write only `usage_records`. If a future change grants it
INSERT/UPDATE/DELETE anywhere else, a compromised gateway could mint an admin
key, so that is asserted directly rather than left to a reading of the SQL.
"""

from __future__ import annotations

import re

import pytest

from app.infrastructure.db_roles import (
    GATEWAY_WRITABLE_TABLES,
    RoleSpec,
    _quote_ident,
    _quote_literal,
    _spec_from_url,
    build_statements,
)

GATEWAY = RoleSpec(name="nexus_gateway", password="gw-pass", profile="gateway")
ADMIN = RoleSpec(name="nexus_admin", password="admin-pass", profile="admin")

WRITE_VERBS = ("INSERT", "UPDATE", "DELETE")

# A GRANT of one or more privileges on a target to a role, e.g.
# `GRANT SELECT, INSERT ON usage_records TO "nexus_gateway";`
_GRANT = re.compile(
    r'GRANT\s+(?P<privs>.+?)\s+ON\s+(?P<target>.+?)\s+TO\s+"(?P<role>[^"]+)"',
    re.IGNORECASE,
)


def _grants_to(statements: list[str], role: str) -> list[tuple[str, str]]:
    """(privileges, target) for every GRANT to `role`, targets lower-cased."""
    out: list[tuple[str, str]] = []
    for statement in statements:
        match = _GRANT.search(statement)
        if match and match.group("role") == role:
            out.append((match.group("privs").upper(), match.group("target").lower()))
    return out


def test_gateway_can_read_all_tables():
    statements = build_statements([GATEWAY], database="nexus")
    grants = _grants_to(statements, "nexus_gateway")
    assert any(
        "SELECT" in privs and "all tables in schema public" in target for privs, target in grants
    )


def test_gateway_may_write_only_usage_records():
    statements = build_statements([GATEWAY], database="nexus")
    for privs, target in _grants_to(statements, "nexus_gateway"):
        if any(verb in privs for verb in WRITE_VERBS):
            # The only writable target is the named usage table.
            assert '"usage_records"' in target, (privs, target)


def test_gateway_privileges_are_revoked_before_regrant():
    # Declarative, not additive: a prior over-grant cannot survive a redeploy.
    statements = build_statements([GATEWAY], database="nexus")
    assert any(
        statement.upper().startswith("REVOKE ALL ON ALL TABLES") and "nexus_gateway" in statement
        for statement in statements
    )


def test_gateway_writable_set_is_exactly_the_named_tables():
    statements = build_statements([GATEWAY], database="nexus")
    insert_targets = {
        target for privs, target in _grants_to(statements, "nexus_gateway") if "INSERT" in privs
    }
    assert insert_targets == {f'"{table}"' for table in GATEWAY_WRITABLE_TABLES}


def test_admin_has_full_dml_on_all_tables():
    statements = build_statements([ADMIN], database="nexus")
    grants = _grants_to(statements, "nexus_admin")
    all_tables = next(privs for privs, target in grants if "all tables in schema public" in target)
    for verb in ("SELECT", *WRITE_VERBS):
        assert verb in all_tables


def test_role_is_created_or_password_rotated_idempotently():
    statements = build_statements([GATEWAY], database="nexus")
    block = next(s for s in statements if s.startswith("DO $do$"))
    assert "CREATE ROLE" in block
    assert "ALTER ROLE" in block
    assert "pg_roles" in block


def test_password_literal_escapes_single_quotes():
    spec = RoleSpec(name="nexus_gateway", password="pa'ss", profile="gateway")
    block = next(s for s in build_statements([spec], database="nexus") if s.startswith("DO $do$"))
    assert "'pa''ss'" in block


def test_identifier_quoting_rejects_unsafe_names():
    with pytest.raises(ValueError):
        _quote_ident('nexus"; DROP ROLE admin; --')
    assert _quote_ident("nexus_gateway") == '"nexus_gateway"'


def test_quote_literal_wraps_and_doubles():
    assert _quote_literal("abc") == "'abc'"
    assert _quote_literal("a'b") == "'a''b'"


def test_spec_reads_name_and_password_from_url():
    spec = _spec_from_url(
        "postgresql+asyncpg://nexus_gateway:s3cret@postgres:5432/nexus", "gateway"
    )
    assert spec.name == "nexus_gateway"
    assert spec.password == "s3cret"
    assert spec.profile == "gateway"


def test_spec_rejects_a_url_without_credentials():
    with pytest.raises(ValueError):
        _spec_from_url("postgresql+asyncpg://postgres:5432/nexus", "gateway")
