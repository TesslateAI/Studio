"""Runtime-field handling for the project create payload/helper."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    from datetime import datetime, timezone

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "rt.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("TESSLATE_STUDIO_HOME", str(tmp_path / "studio-home"))

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


async def _load_project(maker, pid: uuid.UUID):
    from app.models import Project

    async with maker() as s:
        r = await s.execute(select(Project).where(Project.id == pid))
        return r.scalar_one()


def _make_user() -> Mock:
    user = Mock()
    user.id = uuid.uuid4()
    user.default_team_id = None
    return user


async def _run_import(maker, runtime: str | None, src: Path):
    from app.routers.projects import create_project_from_payload
    from app.schemas import ProjectCreate

    user = _make_user()
    payload = ProjectCreate(
        name=f"proj-{runtime or 'none'}-{uuid.uuid4().hex[:6]}",
        source_type="base",
        import_path=str(src),
        runtime=runtime,
    )
    async with maker() as db:
        # Patch the background task path so that even if runtime branch
        # picks the template flow, we don't actually try to scaffold.
        with patch("app.routers.projects.get_task_manager"):
            result = await create_project_from_payload(payload, current_user=user, db=db)
    return result["project"]


@pytest.mark.parametrize("runtime", ["local", "docker", "k8s"])
def test_runtime_stored_verbatim(migrated_sqlite, tmp_path: Path, runtime: str) -> None:
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    src = tmp_path / f"src-{runtime}"
    src.mkdir()

    project = asyncio.run(_run_import(maker, runtime, src))
    row = asyncio.run(_load_project(maker, project.id))
    assert row.runtime == runtime

    asyncio.run(engine.dispose())


def test_runtime_null_uses_deployment_mode_default(
    migrated_sqlite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    from app.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    src = tmp_path / "src-desktop"
    src.mkdir()

    project = asyncio.run(_run_import(maker, None, src))
    row = asyncio.run(_load_project(maker, project.id))
    assert row.runtime == "local"

    # Now switch to docker mode and re-check the mapping.
    monkeypatch.setenv("DEPLOYMENT_MODE", "docker")
    get_settings.cache_clear()

    src2 = tmp_path / "src-docker"
    src2.mkdir()
    project2 = asyncio.run(_run_import(maker, None, src2))
    row2 = asyncio.run(_load_project(maker, project2.id))
    assert row2.runtime == "docker"

    asyncio.run(engine.dispose())
    get_settings.cache_clear()
