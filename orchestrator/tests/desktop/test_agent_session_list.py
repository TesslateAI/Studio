"""Filter matrix for /api/desktop/agents/sessions."""

from __future__ import annotations

import os
import uuid
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
    db_path = tmp_path / "sessions.db"
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
def harness(migrated_sqlite):
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
    yield app, maker, fake_user, engine


def test_session_filter_matrix(harness) -> None:
    import asyncio

    from app.models import AgentTaskDirectory, Directory
    from app.services.agent_tickets import create_ticket

    app, maker, user, engine = harness
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    state: dict[str, uuid.UUID] = {}

    async def _seed():
        async with maker() as s:
            t1 = await create_ticket(s, project_id=project_a, title="a1")
            t2 = await create_ticket(s, project_id=project_a, title="a2")
            t3 = await create_ticket(s, project_id=project_b, title="b1")
            t2.status = "completed"
            dir_local = Directory(
                id=uuid.uuid4(),
                user_id=user.id,
                path="/tmp/a",
                runtime="local",
            )
            dir_docker = Directory(
                id=uuid.uuid4(),
                user_id=user.id,
                path="/tmp/b",
                runtime="docker",
            )
            s.add_all([dir_local, dir_docker])
            await s.flush()
            s.add_all(
                [
                    AgentTaskDirectory(ticket_id=t1.id, directory_id=dir_local.id),
                    AgentTaskDirectory(ticket_id=t3.id, directory_id=dir_docker.id),
                ]
            )
            await s.commit()
            state["t1"] = t1.id
            state["t2"] = t2.id
            state["t3"] = t3.id
            state["dir_local"] = dir_local.id
            state["dir_docker"] = dir_docker.id

    asyncio.run(_seed())

    with TestClient(app) as client:
        all_sessions = client.get("/api/desktop/agents/sessions").json()["sessions"]
        assert len(all_sessions) == 3
        assert all(s["source"] == "local" for s in all_sessions)

        by_project = client.get(
            "/api/desktop/agents/sessions", params={"project_id": str(project_a)}
        ).json()["sessions"]
        assert {s["id"] for s in by_project} == {str(state["t1"]), str(state["t2"])}

        by_status = client.get(
            "/api/desktop/agents/sessions", params={"status": "completed"}
        ).json()["sessions"]
        assert [s["id"] for s in by_status] == [str(state["t2"])]

        by_dir = client.get(
            "/api/desktop/agents/sessions",
            params={"directory_id": str(state["dir_local"])},
        ).json()["sessions"]
        assert [s["id"] for s in by_dir] == [str(state["t1"])]

        by_runtime = client.get(
            "/api/desktop/agents/sessions", params={"runtime": "docker"}
        ).json()["sessions"]
        assert [s["id"] for s in by_runtime] == [str(state["t3"])]

    asyncio.run(engine.dispose())


def test_diff_endpoint_skeleton(harness) -> None:
    import asyncio

    from app.services.agent_tickets import create_ticket

    app, maker, _user, engine = harness
    project_id = uuid.uuid4()

    async def _seed():
        async with maker() as s:
            t = await create_ticket(s, project_id=project_id, title="x")
            await s.commit()
            return t.id

    ticket_id = asyncio.run(_seed())
    with TestClient(app) as client:
        resp = client.get(f"/api/desktop/agents/{ticket_id}/diff")
        assert resp.status_code == 200
        assert resp.json() == {
            "ticket_id": str(ticket_id),
            "trajectory": [],
            "diff": "",
        }
        missing = client.get(f"/api/desktop/agents/{uuid.uuid4()}/diff")
        assert missing.status_code == 404

    asyncio.run(engine.dispose())
