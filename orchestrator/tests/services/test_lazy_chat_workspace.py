"""Unit tests for ``services.lazy_chat_workspace``.

Mirrors ``tests/services/automations/test_lazy_workspace.py``: real
schema via Alembic-on-SQLite, real ORM, no mocks.
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
from sqlalchemy import event, select
from sqlalchemy import insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "lazy_chat_workspace.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
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


async def _seed_user(db) -> uuid.UUID:
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"chatws-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Chat WS User",
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


@pytest.mark.asyncio
async def test_first_call_creates_workspace(session_maker):
    from app.models import PROJECT_KIND_WORKSPACE
    from app.services.lazy_chat_workspace import ensure_user_default_workspace

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        project = await ensure_user_default_workspace(user_id, db)
        await db.commit()

        assert project.name == "~workspace~"
        assert project.project_kind == PROJECT_KIND_WORKSPACE
        assert project.compute_tier == "none"
        assert project.runtime is None
        assert project.visibility == "private"
        assert project.default_contract_template == {}
        assert project.owner_id == user_id
        assert project.slug.startswith("workspace-")


@pytest.mark.asyncio
async def test_second_call_returns_same_row(session_maker):
    from app.services.lazy_chat_workspace import ensure_user_default_workspace

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        first = await ensure_user_default_workspace(user_id, db)
        await db.commit()

        second = await ensure_user_default_workspace(user_id, db)
        await db.commit()

        assert first.id == second.id
        assert first.slug == second.slug


@pytest.mark.asyncio
async def test_no_personal_team_raises_lookup_error(session_maker):
    from app.services.lazy_chat_workspace import ensure_user_default_workspace

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await db.commit()

        with pytest.raises(LookupError):
            await ensure_user_default_workspace(user_id, db)


@pytest.mark.asyncio
async def test_only_one_workspace_in_table_after_double_call(session_maker):
    from app.models import PROJECT_KIND_WORKSPACE, Project
    from app.services.lazy_chat_workspace import ensure_user_default_workspace

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        await ensure_user_default_workspace(user_id, db)
        await db.commit()
        await ensure_user_default_workspace(user_id, db)
        await db.commit()

        rows = (
            (
                await db.execute(
                    select(Project)
                    .where(Project.owner_id == user_id)
                    .where(Project.name == "~workspace~")
                    .where(Project.project_kind == PROJECT_KIND_WORKSPACE)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_per_user_workspace_does_not_collide(session_maker):
    """Two distinct users get two distinct workspaces."""
    from app.services.lazy_chat_workspace import ensure_user_default_workspace

    async with session_maker() as db:
        user_a = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_a)
        user_b = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_b)
        await db.commit()

        ws_a = await ensure_user_default_workspace(user_a, db)
        ws_b = await ensure_user_default_workspace(user_b, db)
        await db.commit()

        assert ws_a.id != ws_b.id
        assert ws_a.slug != ws_b.slug
        assert ws_a.owner_id == user_a
        assert ws_b.owner_id == user_b


@pytest.mark.asyncio
async def test_distinct_from_automation_workspace(session_maker):
    """The chat workspace and the automation workspace coexist as separate rows."""
    from app.models import Project
    from app.services.automations.lazy_workspace import (
        ensure_user_automation_workspace,
    )
    from app.services.lazy_chat_workspace import ensure_user_default_workspace

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await _seed_personal_team(db, user_id=user_id)
        await db.commit()

        chat_ws = await ensure_user_default_workspace(user_id, db)
        auto_ws = await ensure_user_automation_workspace(user_id, db)
        await db.commit()

        assert chat_ws.id != auto_ws.id
        assert chat_ws.name == "~workspace~"
        assert auto_ws.name == "~automations~"

        rows = (
            (await db.execute(select(Project).where(Project.owner_id == user_id))).scalars().all()
        )
        assert len(rows) == 2
