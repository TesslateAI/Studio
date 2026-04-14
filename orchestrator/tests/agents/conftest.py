"""Shared fixtures for multi-agent orchestration tests.

Each test gets a fresh SQLite file migrated to ``head`` by alembic so the
schema matches production. Async sessions are created against that DB.

SQLite foreign keys are disabled by default, so tests can insert
``agent_tasks`` rows without seeding full ``projects`` / ``users`` graphs.
The schema check still verifies the FK *columns* exist.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "agents.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()

    orchestrator_dir = Path(__file__).resolve().parents[2]
    original_cwd = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original_cwd)

    yield url
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def async_session(sqlite_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(sqlite_url, future=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(sqlite_url: str):
    engine = create_async_engine(sqlite_url, future=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


def make_project_id() -> uuid.UUID:
    return uuid.uuid4()
