"""TestClient coverage for the desktop agent-ticket endpoints."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "router.db"
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
def app_and_maker(migrated_sqlite):
    from app.database import get_db
    from app.routers import desktop
    from app.users import current_active_user

    engine = create_async_engine(migrated_sqlite, future=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with maker() as s:
            yield s

    fake_user = Mock()
    fake_user.id = uuid.uuid4()

    app = FastAPI()
    app.include_router(desktop.router)
    app.dependency_overrides[current_active_user] = lambda: fake_user
    app.dependency_overrides[get_db] = override_db

    yield app, maker, engine


def test_list_and_approve_roundtrip(app_and_maker) -> None:
    import asyncio

    app, maker, engine = app_and_maker
    project_id = uuid.uuid4()

    from app.services.agent_tickets import create_ticket

    async def _seed():
        async with maker() as s:
            await create_ticket(s, project_id=project_id, title="one")
            t2 = await create_ticket(
                s,
                project_id=project_id,
                title="two",
                requires_approval_for=["deploy"],
            )
            t2.status = "awaiting_approval"
            t2.updated_at = datetime.now(timezone.utc)
            await s.commit()
            return t2.id

    t2_id = asyncio.run(_seed())

    with TestClient(app) as client:
        resp = client.get("/api/desktop/agents/tickets")
        assert resp.status_code == 200
        tickets = resp.json()["tickets"]
        assert len(tickets) == 2
        assert {t["ref_id"] for t in tickets} == {"TSK-0001", "TSK-0002"}

        # Filter by status.
        filtered = client.get(
            "/api/desktop/agents/tickets", params={"status": "awaiting_approval"}
        ).json()["tickets"]
        assert len(filtered) == 1
        assert filtered[0]["id"] == str(t2_id)

        # Approve.
        approve = client.post(f"/api/desktop/agents/{t2_id}/approve")
        assert approve.status_code == 200
        assert approve.json() == {"ticket_id": str(t2_id), "status": "queued"}

        # Approve nonexistent → 404.
        missing = client.post(f"/api/desktop/agents/{uuid.uuid4()}/approve")
        assert missing.status_code == 404

    asyncio.run(engine.dispose())
