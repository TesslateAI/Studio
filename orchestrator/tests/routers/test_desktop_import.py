"""Coverage for POST /api/desktop/import."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    """SQLite lacks ``now()``; register it so server_default=func.now() works."""
    from datetime import datetime

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "imp.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path / "studio-home"))

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
def app_env(migrated_sqlite):
    from app.database import get_db
    from app.routers import desktop
    from app.users import current_active_user

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with maker() as s:
            yield s

    user = Mock()
    user.id = uuid.uuid4()
    user.default_team_id = None

    app = FastAPI()
    app.include_router(desktop.router)
    app.dependency_overrides[current_active_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    yield app, user, engine, maker


def test_import_happy_path_creates_local_project(app_env, tmp_path: Path) -> None:
    app, user, engine, maker = app_env
    src = tmp_path / "myrepo"
    src.mkdir()
    (src / "README.md").write_text("hi", encoding="utf-8")

    with TestClient(app) as client:
        resp = client.post(
            "/api/desktop/import",
            json={"name": "MyRepo", "path": str(src)},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project"]["name"] == "MyRepo"
        project_id = body["project"]["id"]

    async def _load():
        from app.models import Project

        async with maker() as s:
            r = await s.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
            return r.scalar_one()

    row = asyncio.run(_load())
    assert row.runtime == "local"
    assert row.source_path == os.path.realpath(str(src))
    assert row.owner_id == user.id

    # Project root should be a symlink pointing at the source on POSIX.
    # Note: _get_project_root calls .resolve() which follows symlinks, so we
    # reconstruct the unresolved path to verify the symlink itself.
    from app.services.desktop_paths import ensure_opensail_home

    home = ensure_opensail_home(os.environ.get("OPENSAIL_HOME"))
    unresolved_root = home / "projects" / f"{row.slug}-{row.id}"
    if os.name != "nt":
        assert unresolved_root.is_symlink()
        assert os.path.realpath(unresolved_root) == os.path.realpath(str(src))
    else:
        assert (unresolved_root / ".tesslate-source").exists()

    asyncio.run(engine.dispose())


def test_import_missing_path_returns_400(app_env, tmp_path: Path) -> None:
    app, _user, engine, _ = app_env
    with TestClient(app) as client:
        resp = client.post(
            "/api/desktop/import",
            json={"name": "X", "path": str(tmp_path / "nope")},
        )
        assert resp.status_code == 400
    asyncio.run(engine.dispose())


def test_import_path_is_file_returns_400(app_env, tmp_path: Path) -> None:
    app, _user, engine, _ = app_env
    f = tmp_path / "a-file.txt"
    f.write_text("hi", encoding="utf-8")
    with TestClient(app) as client:
        resp = client.post(
            "/api/desktop/import",
            json={"name": "X", "path": str(f)},
        )
        assert resp.status_code == 400
    asyncio.run(engine.dispose())


def test_import_duplicate_source_path_returns_409(app_env, tmp_path: Path) -> None:
    app, _user, engine, _ = app_env
    src = tmp_path / "dup"
    src.mkdir()
    with TestClient(app) as client:
        r1 = client.post("/api/desktop/import", json={"name": "A", "path": str(src)})
        assert r1.status_code == 200, r1.text
        r2 = client.post("/api/desktop/import", json={"name": "B", "path": str(src)})
        assert r2.status_code == 409
    asyncio.run(engine.dispose())
