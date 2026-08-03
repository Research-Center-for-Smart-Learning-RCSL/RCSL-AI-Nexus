"""Alembic environment.

Runs as a one-shot Compose service rather than from an application
entrypoint, because three containers start from the same image and would
otherwise race each other. See docs/architecture/deployment.md section 9.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context
from app.adapters.persistence.sqlalchemy_models import Base
from app.infrastructure.config import get_settings

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False` is not a preference. The default is
    # True, and `alembic.ini` names only root, sqlalchemy and alembic — so
    # every logger that already exists and is not one of those is set
    # `disabled = True`, which includes the whole `app.*` tree. A disabled
    # logger reports its level normally and drops every record, so the effect
    # is invisible in anything that inspects levels.
    #
    # The migrate service runs in its own process, so a deployment is not
    # affected. The test session is: from the first integration test onward,
    # every application log line was silently discarded, which is how
    # tests/unit/test_logging_config.py came to pass alone and fail in the
    # suite. Found 2026-08-03, the same day as the sibling defect — the one
    # where the perimeter's own explanation of a refusal was never emitted.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# The migration account is a third database user with DDL rights, separate
# from the read-only gateway account and the read-write admin account.
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
