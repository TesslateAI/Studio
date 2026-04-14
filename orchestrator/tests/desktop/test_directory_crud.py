"""CRUD coverage for /api/desktop/directories."""

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
    db_path = tmp_path / "dir.db"
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
def app_and_user(migrated_sqlite):
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
    yield app, fake_user, engine, maker


def test_create_directory_dedup_same_path(app_and_user, tmp_path: Path) -> None:
    import asyncio

    app, _user, engine, _ = app_and_user
    p = tmp_path / "workspace"
    p.mkdir()

    with TestClient(app) as client:
        r1 = client.post("/api/desktop/directories", json={"path": str(p)})
        r2 = client.post("/api/desktop/directories", json={"path": str(p)})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]
        listed = client.get("/api/desktop/directories").json()["directories"]
        assert len(listed) == 1

    asyncio.run(engine.dispose())


def test_create_directory_detects_git_root(app_and_user, tmp_path: Path) -> None:
    import asyncio

    app, _user, engine, _ = app_and_user
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "src"
    sub.mkdir()

    with TestClient(app) as client:
        r = client.post("/api/desktop/directories", json={"path": str(sub)})
        assert r.status_code == 200
        body = r.json()
        assert body["git_root"] == str(repo.resolve())

    asyncio.run(engine.dispose())


def test_list_scoped_to_user(app_and_user, tmp_path: Path) -> None:
    import asyncio

    from app.database import get_db
    from app.models import Directory
    from app.users import current_active_user

    app, user, engine, maker = app_and_user

    other_user_id = uuid.uuid4()

    async def _seed_other():
        async with maker() as s:
            s.add(
                Directory(
                    id=uuid.uuid4(),
                    user_id=other_user_id,
                    path="/tmp/other",
                )
            )
            await s.commit()

    asyncio.run(_seed_other())

    p = tmp_path / "mine"
    p.mkdir()
    with TestClient(app) as client:
        client.post("/api/desktop/directories", json={"path": str(p)})
        listed = client.get("/api/desktop/directories").json()["directories"]
        assert len(listed) == 1
        assert listed[0]["path"] == str(p.resolve())

    # Now swap user; the other user should see their own row.
    other = Mock()
    other.id = other_user_id
    app.dependency_overrides[current_active_user] = lambda: other
    with TestClient(app) as client:
        listed = client.get("/api/desktop/directories").json()["directories"]
        assert len(listed) == 1
        assert listed[0]["path"] == "/tmp/other"

    _ = get_db  # silence unused
    asyncio.run(engine.dispose())


def test_delete_directory_returns_204(app_and_user, tmp_path: Path) -> None:
    import asyncio

    app, _user, engine, _ = app_and_user
    p = tmp_path / "ws"
    p.mkdir()
    with TestClient(app) as client:
        created = client.post("/api/desktop/directories", json={"path": str(p)}).json()
        dir_id = created["id"]
        resp = client.delete(f"/api/desktop/directories/{dir_id}")
        assert resp.status_code == 204
        assert client.get("/api/desktop/directories").json()["directories"] == []
        missing = client.delete(f"/api/desktop/directories/{uuid.uuid4()}")
        assert missing.status_code == 404

    asyncio.run(engine.dispose())
