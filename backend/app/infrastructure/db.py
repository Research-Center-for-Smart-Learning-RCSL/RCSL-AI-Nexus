"""Database engine and session lifecycle.

Each service supplies its own `DATABASE_URL`, which is how the least-privilege
split from docs/architecture/security.md section 6 is realised: the gateway
connects as a read-only account, the admin entrances as a read-write one, and
the migration job as a third with DDL rights. Nothing in the application layer
knows or cares which it got; the grants do the enforcing.
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
