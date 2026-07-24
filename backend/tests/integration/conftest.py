"""Shared setup for tests that touch a real database.

The schema comes from Alembic, not from `Base.metadata.create_all`. Building
it from the ORM meant the migrations were never executed by any test, so the
two could drift apart and nothing would notice until a deployment; it also
produced a database whose tables existed with no version row, which then broke
`alembic upgrade` by hand.

Session parameters mirror `infrastructure/db.py`. They differed before, and
the difference fell exactly on the behaviour under test: with autoflush on, an
ORM-enabled UPDATE flushes pending inserts first, so a save followed by a
conditional delete behaves differently here than in production.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def reset_schema(url: str) -> None:
    """Drop everything and rebuild from migrations.

    `downgrade base` rather than `drop_all`, so the down path is exercised on
    every run instead of being written and never executed.
    """
    os.environ["DATABASE_URL"] = url
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    reset_schema(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


def make_session_factory(url: str) -> async_sessionmaker:
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
