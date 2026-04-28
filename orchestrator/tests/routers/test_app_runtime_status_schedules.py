"""Tests for the schedules projection on ``/api/app-installs/{id}/schedules``.

The Phase 1 hard reset dropped ``agent_schedules``. The schedules endpoint
now projects ``automation_definitions`` rows scoped by
``target_project_id == app_instance.project_id``, paired with their first
``automation_triggers`` row to fill the legacy ``ScheduleRow`` shape
(``cron`` / ``trigger_kind``) the existing UI renders.

Tested through the helper :func:`_list_instance_schedules` rather than the
full HTTP stack — it carries all the projection logic; the route handler is
a thin auth-and-load wrapper.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models, models_automations  # noqa: F401  -- register tables
from app.database import Base
from app.models import (
    PROJECT_KIND_APP_RUNTIME,
    Project,
    Team,
    User,
)
from app.models_automations import (
    AutomationDefinition,
    AutomationTrigger,
)
from app.routers.app_runtime_status import _list_instance_schedules


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def runtime_project(db: AsyncSession) -> Project:
    user_id = uuid.uuid4()
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            name="X",
            username=f"user-{user_id.hex[:10]}",
            slug=f"user-{user_id.hex[:10]}",
        )
    )
    team_id = uuid.uuid4()
    db.add(
        Team(
            id=team_id,
            slug=f"team-{team_id.hex[:10]}",
            name="T",
            is_personal=True,
            created_by_id=user_id,
        )
    )
    await db.flush()

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name="Runtime",
        slug=f"rt-{project_id.hex[:6]}",
        owner_id=user_id,
        team_id=team_id,
        visibility="team",
        project_kind=PROJECT_KIND_APP_RUNTIME,
        volume_id=f"vol-{project_id.hex[:8]}",
    )
    db.add(project)
    await db.flush()
    return project


# ---------------------------------------------------------------------------
# Shape projection.
# ---------------------------------------------------------------------------


async def test_returns_empty_list_when_no_definitions(
    db: AsyncSession, runtime_project: Project
) -> None:
    rows = await _list_instance_schedules(db, target_project_id=runtime_project.id)
    assert rows == []


async def test_projects_definition_with_first_trigger(
    db: AsyncSession, runtime_project: Project
) -> None:
    user_id = runtime_project.owner_id
    defn = AutomationDefinition(
        id=uuid.uuid4(),
        name="Weekly digest",
        owner_user_id=user_id,
        team_id=runtime_project.team_id,
        workspace_scope="target_project",
        target_project_id=runtime_project.id,
        contract={"max_compute_tier": 1},
        max_compute_tier=1,
        is_active=True,
        depth=0,
    )
    db.add(defn)
    await db.flush()
    trig = AutomationTrigger(
        id=uuid.uuid4(),
        automation_id=defn.id,
        kind="cron",
        config={"cron": "0 9 * * 1"},
        is_active=True,
        last_run_at=datetime.now(tz=UTC),
    )
    db.add(trig)
    await db.flush()

    rows = await _list_instance_schedules(db, target_project_id=runtime_project.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.id == defn.id
    assert row.name == "Weekly digest"
    assert row.cron == "0 9 * * 1"
    assert row.trigger_kind == "cron"
    assert row.last_run_at is not None
    assert row.enabled is True


async def test_projects_definition_without_trigger_falls_back_to_manual(
    db: AsyncSession, runtime_project: Project
) -> None:
    """A definition without a trigger row still surfaces (with kind='manual')
    so the UI can render it; the canonical /api/automations PATCH flow is
    where users add triggers."""
    defn = AutomationDefinition(
        id=uuid.uuid4(),
        name="Manual only",
        owner_user_id=runtime_project.owner_id,
        team_id=runtime_project.team_id,
        workspace_scope="target_project",
        target_project_id=runtime_project.id,
        contract={"max_compute_tier": 0},
        is_active=False,
        depth=0,
    )
    db.add(defn)
    await db.flush()

    rows = await _list_instance_schedules(db, target_project_id=runtime_project.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.trigger_kind == "manual"
    assert row.cron is None
    assert row.enabled is False


async def test_does_not_leak_definitions_from_other_projects(
    db: AsyncSession, runtime_project: Project
) -> None:
    """Sanity: definitions scoped to a different project don't leak in."""
    other_project_id = uuid.uuid4()
    other_project = Project(
        id=other_project_id,
        name="Other",
        slug=f"other-{other_project_id.hex[:6]}",
        owner_id=runtime_project.owner_id,
        team_id=runtime_project.team_id,
        visibility="team",
        project_kind=PROJECT_KIND_APP_RUNTIME,
    )
    db.add(other_project)
    await db.flush()

    db.add(
        AutomationDefinition(
            id=uuid.uuid4(),
            name="Other project automation",
            owner_user_id=runtime_project.owner_id,
            team_id=runtime_project.team_id,
            workspace_scope="target_project",
            target_project_id=other_project_id,
            contract={"max_compute_tier": 0},
            is_active=True,
            depth=0,
        )
    )
    await db.flush()

    rows = await _list_instance_schedules(db, target_project_id=runtime_project.id)
    assert rows == []
