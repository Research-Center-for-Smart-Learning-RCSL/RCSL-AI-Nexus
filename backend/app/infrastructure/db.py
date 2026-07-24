"""Database engine and session lifecycle.

`DATABASE_URL` is per service, which is the hook the least-privilege split in
docs/architecture/security.md section 6 would use.

**That split is not implemented.** Compose gives every backend service the
same `env_file`, so the gateway, both admin entrances and the migration job
all connect as one account with DDL rights. This comment previously described
the split in the present tense, which is worse than silence: it reads as
documentation of a shipped control and stops anyone looking for the risk.

Implementing it means three roles with grants, three URLs, and a note that the
gateway does need INSERT on `usage_records` even though it must not write
`api_keys`, `routing_policies`, or `users`.
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
