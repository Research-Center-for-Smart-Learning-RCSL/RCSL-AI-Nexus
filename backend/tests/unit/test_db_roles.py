"""The database role split (security.md section 6).

The property under test is a security boundary: the gateway account may write
only the tables named in `GATEWAY_WRITABLE_TABLES`. If a future change grants it
INSERT/UPDATE/DELETE anywhere else, a compromised gateway could mint an admin
key, so that is asserted directly rather than left to a reading of the SQL.

Since 2026-08-08 there is a second, opposite property. `prompt_logs` is the one
table the gateway may write and may **not** read: it holds the plaintext of what
researchers typed, and the process holding that account is the one exposed to
the internet. The blanket `GRANT SELECT ON ALL TABLES` puts the privilege there
by default, so the revoke has to come after it — an ordering that is invisible
in a diff and load-bearing in effect, which is why it is asserted here.
"""

from __future__ import annotations

import re

import pytest

from app.infrastructure.db_roles import (
    GATEWAY_DENIED_READ_TABLES,
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


def test_gateway_may_write_only_the_named_tables():
    statements = build_statements([GATEWAY], database="nexus")
    permitted = {f'"{table}"' for table in GATEWAY_WRITABLE_TABLES}
    for privs, target in _grants_to(statements, "nexus_gateway"):
        if any(verb in privs for verb in WRITE_VERBS):
            assert target in permitted, (privs, target)


def test_gateway_cannot_read_prompt_logs():
    """Appending its own transcripts must not become reading everyone's.

    The same asymmetry the knowledge base already makes in the other direction:
    Qdrant hands the gateway a read-only key so retrieving a passage cannot
    become writing one. Here the untrusted side gets write and not read, for the
    same reason — exactly the one verb its job needs.
    """
    statements = build_statements([GATEWAY], database="nexus")
    revokes = [
        s for s in statements if s.upper().startswith("REVOKE SELECT ON") and "nexus_gateway" in s
    ]
    for table in GATEWAY_DENIED_READ_TABLES:
        assert any(f'"{table}"' in s for s in revokes), f"SELECT on {table} is not revoked"


def test_the_deny_read_revoke_comes_after_the_blanket_select_grant():
    """Ordering, which is the whole of whether the previous test means anything.

    `GRANT SELECT ON ALL TABLES` includes `prompt_logs`. A revoke placed before
    it is undone in the same transaction, and both statements are still present
    for the assertion above to find — so the ordering has to be asserted
    separately or a reordering would pass every other test in this file.
    """
    statements = build_statements([GATEWAY], database="nexus")
    blanket = next(
        i for i, s in enumerate(statements) if s.upper().startswith("GRANT SELECT ON ALL TABLES")
    )
    revoke = next(i for i, s in enumerate(statements) if s.upper().startswith("REVOKE SELECT ON"))
    assert revoke > blanket


def test_prompt_logs_is_both_writable_and_unreadable():
    """The pair, stated together. Dropping either half is a silent change of
    meaning: without the INSERT the gateway cannot record a transcript at all
    and the API-key debug window becomes decorative; without the revoke the
    internet-facing process can read every tenant's conversations."""
    assert "prompt_logs" in GATEWAY_WRITABLE_TABLES
    assert "prompt_logs" in GATEWAY_DENIED_READ_TABLES


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
