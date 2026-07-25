"""Database engine and session lifecycle.

`DATABASE_URL` is per service, and that is the least-privilege split in
docs/architecture/security.md section 6: each service mounts its own account's
URL as the `database_url` secret. The gateway's account may read every table
and INSERT only into `usage_records`; the two admin entrances share an account
with full DML and no DDL; the `migrate` job connects as the schema owner and,
via app.infrastructure.db_roles, creates the other two roles and their grants.

This module is unaware of which account it holds: it is handed a URL and opens
a pool. The privilege boundary lives in the grants, enforced by Postgres, not
in application code that could forget it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            # A long-lived 24/7 process against a database that may be
            # restarted for maintenance; recycling avoids serving a request on
            # a connection the server has already dropped.
            pool_recycle=1800,
            # Set explicitly rather than left at the 5 + 10 default. A request
            # holds its connection from the first query (API-key auth) until
            # the transaction commits, which for a stream is after the whole
            # response — and an audited action opens a second, independent
            # connection while the first is still held. So the ceiling has to
            # comfortably exceed the expected concurrent request count, not sit
            # near it. Postgres 17's default `max_connections` is 100, and the
            # three backend services share it, so this stays well under a third.
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            echo=False,
        )
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("init_engine has not been called")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """One transaction per unit of work.

    Repositories never commit. The scope owner does, so a use case touching
    several repositories either lands entirely or not at all.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
