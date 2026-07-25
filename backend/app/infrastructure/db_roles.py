"""Per-service database roles and their grants (security.md section 6).

The split this implements: three Postgres accounts, not one.

- The **owner** (`POSTGRES_USER`) owns the schema and runs migrations. Only the
  `migrate` job connects as it, and this module runs as it.
- The **gateway** account may read every table and may INSERT into
  `usage_records`, nothing more. It must not be able to write `api_keys`,
  `routing_policies`, or `users`, so a compromised public gateway cannot mint
  itself an admin key. "Read only" is the wrong shape: the restriction is per
  table, so the writable set is named explicitly below.
- The **admin** account, shared by both admin entrances (§1, same trust tier),
  has full DML on every table and no DDL.

Run as `python -m app.infrastructure.db_roles`, after `alembic upgrade head`
and before `provision`, from the `migrate` service. Idempotent: it re-asserts
the exact privilege set on every deploy, so a table added by a later migration
is regranted (and the gateway's writable set stays exactly this one table)
without anyone editing grants by hand.

Roles are identified by the username inside each service's own connection URL,
so the URL secret is the single source of truth for both the account name and
its password; this module never invents a name the deployment did not already
commit to.

Why the SQL is assembled as text with hand-quoted identifiers and literals:
`GRANT`, `CREATE ROLE`, and a role password are DDL, which no driver
parameterises. The quoting helpers below are the standard, minimal escapers
(double the quote character), safe under `standard_conforming_strings`, which
is on by default. Role names are additionally constrained to a strict pattern,
because they come from a URL and a name is an identifier we control, not
untrusted input.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.config import get_settings

logger = logging.getLogger(__name__)

# The one table the gateway writes. Everything else it may only read. Kept here,
# in code, because it is a security decision that belongs under review, not in a
# deployment file. See security.md section 6.
GATEWAY_WRITABLE_TABLES: tuple[str, ...] = ("usage_records",)

# Where the migrate service sees the other services' connection URLs. Each holds
# the same content that service reads as `/run/secrets/database_url`; mounted
# here under a distinct name so this job can learn their account names.
GATEWAY_URL_FILE = Path("/run/secrets/gateway_database_url")
ADMIN_URL_FILE = Path("/run/secrets/admin_database_url")

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _quote_ident(name: str) -> str:
    if not _IDENT.match(name):
        # Not a general quoter: these names are ours, and anything outside this
        # shape is a misconfiguration we want to fail on rather than escape.
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True, slots=True)
class RoleSpec:
    name: str
    password: str
    profile: str  # "gateway" | "admin"


def _spec_from_url(url: str, profile: str) -> RoleSpec:
    parsed = make_url(url)
    if not parsed.username or parsed.password is None:
        raise ValueError(f"{profile} database URL must carry a username and password")
    return RoleSpec(name=parsed.username, password=parsed.password, profile=profile)


def _role_statements(spec: RoleSpec, *, database: str) -> list[str]:
    """Create-or-update the login role, then set its exact privileges.

    The grants are declarative rather than additive: the gateway's privileges
    are revoked and re-granted so its writable set is always precisely
    `GATEWAY_WRITABLE_TABLES`, regardless of what a previous run left.
    """
    ident = _quote_ident(spec.name)
    literal_name = _quote_literal(spec.name)
    literal_pw = _quote_literal(spec.password)
    db_ident = _quote_ident(database)

    statements = [
        # Create or rotate the password in one idempotent block.
        f"""DO $do$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal_name}) THEN
    ALTER ROLE {ident} WITH LOGIN PASSWORD {literal_pw};
  ELSE
    CREATE ROLE {ident} WITH LOGIN PASSWORD {literal_pw};
  END IF;
END
$do$;""",
        f"GRANT CONNECT ON DATABASE {db_ident} TO {ident};",
        f"GRANT USAGE ON SCHEMA public TO {ident};",
    ]

    if spec.profile == "gateway":
        statements += [
            # Declarative: strip everything, then grant back exactly read-all
            # plus insert on the named tables. This is what keeps a compromised
            # gateway off `api_keys` and `users` even if an earlier run erred.
            f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ident};",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ident};",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ident};",
        ]
        for table in GATEWAY_WRITABLE_TABLES:
            statements.append(f"GRANT INSERT ON {_quote_ident(table)} TO {ident};")
    elif spec.profile == "admin":
        statements += [
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ident};",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ident};",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ident};",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {ident};",
        ]
    else:  # pragma: no cover - guarded by the callers that build specs
        raise ValueError(f"unknown role profile: {spec.profile}")

    return statements


def build_statements(specs: list[RoleSpec], *, database: str) -> list[str]:
    out: list[str] = []
    for spec in specs:
        out.extend(_role_statements(spec, database=database))
    return out


async def apply_statements(owner_url: str, statements: list[str]) -> None:
    """Run the grants as the owner, in one transaction so a failure lands nothing.

    Statements are never logged verbatim, because one of them carries a role
    password.
    """
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                # exec_driver_sql, not execute(text(...)): these are DDL with
                # literal passwords, and text() would read a `:` in a password
                # as a bind parameter. This passes the string straight to the
                # driver.
                await conn.exec_driver_sql(statement)
    finally:
        await engine.dispose()


def _read_url_file(path: Path, profile: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"{profile} database URL secret not mounted at {path}. The role split "
            f"needs it to learn the {profile} account name; see docker-compose.yml."
        )
    return path.read_text(encoding="utf-8").strip()


async def provision_roles() -> None:
    settings = get_settings()
    specs = [
        _spec_from_url(_read_url_file(GATEWAY_URL_FILE, "gateway"), "gateway"),
        _spec_from_url(_read_url_file(ADMIN_URL_FILE, "admin"), "admin"),
    ]
    database = make_url(settings.database_url).database
    if not database:
        raise ValueError("owner DATABASE_URL has no database name")
    statements = build_statements(specs, database=database)
    await apply_statements(settings.database_url, statements)
    logger.info(
        "database roles provisioned: %s",
        ", ".join(f"{spec.name}({spec.profile})" for spec in specs),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(provision_roles())
    return 0


if __name__ == "__main__":
    sys.exit(main())
