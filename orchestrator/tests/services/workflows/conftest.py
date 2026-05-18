"""Fixtures for the workflow engine test suite.

Uses ``Base.metadata.create_all`` against an in-memory SQLite to create
the tables we need without running the full alembic chain. The
alembic-head + SQLite fixture used in ``tests/services/automations/
test_dispatcher.py`` hits a pre-existing migration 0089 SQLite batch
issue (``user_library_themes_theme_id_fkey`` constraint reflection)
that is out of scope for Phase A. The schema we exercise is fully
defined in the SQLAlchemy models, so ``create_all`` is sufficient.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


@pytest.fixture
def session_maker(tmp_path):
    """Yield a session maker bound to a fresh SQLite DB with all tables created.

    Tables come from ``Base.metadata`` so any model imported under
    ``app.models`` / ``app.models_automations`` is created. We import
    those modules first so the metadata is fully populated before
    ``create_all`` runs.
    """
    db_path = tmp_path / "workflows.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    # Importing these populates ``Base.metadata`` with all tables we use.
    import app.models  # noqa: F401
    import app.models_automations  # noqa: F401
    from app.database import Base

    engine = create_async_engine(url, future=True)
    _install_sqlite_now(engine)

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())

    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers (compact copies of the patterns in tests/services/automations/
# test_dispatcher.py — duplicated rather than imported to avoid coupling test
# modules).
# ---------------------------------------------------------------------------


async def seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"test-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Test User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def seed_automation(
    db,
    *,
    owner_user_id: uuid.UUID,
    contract: dict[str, Any] | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="test-multi-step",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract=contract
        if contract is not None
        else {
            "allowed_tools": ["read_file"],
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
        max_compute_tier=0,
        is_active=True,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def seed_event(
    db,
    *,
    automation_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationEvent

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        payload=payload or {"trigger": "test"},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    return evt.id


async def seed_action(
    db,
    *,
    automation_id: uuid.UUID,
    action_type: str,
    config: dict[str, Any] | None = None,
    ordinal: int = 0,
) -> uuid.UUID:
    from app.models_automations import AutomationAction

    act = AutomationAction(
        id=uuid.uuid4(),
        automation_id=automation_id,
        ordinal=ordinal,
        action_type=action_type,
        config=config or {},
    )
    db.add(act)
    await db.flush()
    return act.id


async def seed_marketplace_agent(
    db,
    *,
    is_system: bool = True,
) -> uuid.UUID:
    """Seed a runnable system MarketplaceAgent used by doctor tests.

    The G5 doctor needs a real ``agent_id`` to satisfy develop's
    TC-03 validator on ``agent.run`` actions. Tests that exercise
    ``ensure_doctor_for`` must have at least one runnable agent in
    the DB; this helper seeds the minimal row.
    """
    from sqlalchemy import insert as core_insert

    from app.models import MarketplaceAgent

    agent_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(MarketplaceAgent.__table__).values(
            id=agent_id,
            name=f"test-agent-{suffix}",
            slug=f"test-agent-{suffix}",
            description="seeded for doctor tests",
            category="builder",
            item_type="agent",
            is_active=True,
            is_system=is_system,
            pricing_type="free",
        )
    )
    await db.flush()
    return agent_id


async def seed_run(
    db,
    *,
    automation_id: uuid.UUID,
    event_id: uuid.UUID,
) -> uuid.UUID:
    from app.models_automations import AutomationRun

    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=automation_id,
        event_id=event_id,
        status="running",
        started_at=datetime.now(tz=UTC),
        heartbeat_at=datetime.now(tz=UTC),
    )
    db.add(run)
    await db.flush()
    return run.id
