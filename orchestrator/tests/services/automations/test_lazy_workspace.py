"""Phase 5 — unit tests for ``services.automations.lazy_workspace``.

The fixture pattern mirrors ``test_dispatcher.py`` and ``test_budget.py``:
SQLite at alembic head, so the real Project + Team + User schemas are
in play.

Key invariants under test:

- First call inserts a row.
- Second call returns the SAME row (idempotent).
- Created row has the expected name + project_kind + compute_tier +
  visibility + default_contract_template.
- LookupError when the user has no personal team.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert as core_insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration fixture (same shape as test_dispatcher.py / test_budget.py).
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "lazy_workspace.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"lazy-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Lazy User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_personal_team(db, *, user_id: uuid.UUID) -> uuid.UUID:
    from app.models_team import Team

    team = Team(
        id=uuid.uuid4(),
        name="Personal",
        slug=f"personal-{uuid.uuid4().hex[:8]}",
        is_personal=True,
        created_by_id=user_id,
    )
    db.add(team)
    await db.flush()
    return team.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_call_creates_workspace(session_maker):
    from app.models import PROJECT_KIND_WORKSPACE
    from app.services.automations.lazy_workspace import (
        ensure_user_automation_workspace,
    )

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        project = await ensure_user_automation_workspace(user_id, db)
        await db.commit()

        assert project.name == "~automations~"
        assert project.project_kind == PROJECT_KIND_WORKSPACE
        assert project.compute_tier == "none"
        assert project.runtime is None
        assert project.visibility == "private"
        assert project.default_contract_template == {}
        assert project.owner_id == user_id


@pytest.mark.asyncio
async def test_second_call_returns_same_row(session_maker):
    from app.services.automations.lazy_workspace import (
        ensure_user_automation_workspace,
    )

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        first = await ensure_user_automation_workspace(user_id, db)
        await db.commit()

        second = await ensure_user_automation_workspace(user_id, db)
        await db.commit()

        assert first.id == second.id
        assert first.slug == second.slug


@pytest.mark.asyncio
async def test_no_personal_team_raises_lookup_error(session_maker):
    from app.services.automations.lazy_workspace import (
        ensure_user_automation_workspace,
    )

    async with session_maker() as db:
        user_id = await _seed_user(db)
        # Intentionally NO personal team seeded.
        await db.commit()

        with pytest.raises(LookupError):
            await ensure_user_automation_workspace(user_id, db)


@pytest.mark.asyncio
async def test_only_one_workspace_in_table_after_double_call(session_maker):
    from app.models import PROJECT_KIND_WORKSPACE, Project
    from app.services.automations.lazy_workspace import (
        ensure_user_automation_workspace,
    )

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        await ensure_user_automation_workspace(user_id, db)
        await db.commit()
        await ensure_user_automation_workspace(user_id, db)
        await db.commit()

        rows = (
            await db.execute(
                select(Project)
                .where(Project.owner_id == user_id)
                .where(Project.name == "~automations~")
                .where(Project.project_kind == PROJECT_KIND_WORKSPACE)
            )
        ).scalars().all()
        assert len(rows) == 1
