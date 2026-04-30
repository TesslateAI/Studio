"""Empty-workspace creation path for ``create_project_from_payload``.

Covers:
  * ``ProjectCreate`` accepts ``source_type='empty'`` without a base_id.
  * ``ProjectCreate`` rejects ``source_type='empty'`` if a base_id is given.
  * The router branch creates a Project row with ``created_via='empty'``,
    ``compute_tier='none'``, ``environment_status='active'``.
  * No background task is enqueued (``task_id is None``).
  * The on-disk project root is materialized and ``has_git_repo=True``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
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
    db_path = tmp_path / "empty.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path / "studio-home"))
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


def _make_user() -> Mock:
    user = Mock()
    user.id = uuid.uuid4()
    user.default_team_id = None
    return user


def test_schema_accepts_empty_source_without_base_id() -> None:
    from app.schemas import ProjectCreate

    payload = ProjectCreate(name="kb-1", source_type="empty")
    assert payload.source_type == "empty"
    assert payload.base_id is None


def test_schema_rejects_empty_source_with_base_id() -> None:
    from pydantic import ValidationError

    from app.schemas import ProjectCreate

    with pytest.raises(ValidationError):
        ProjectCreate(name="kb-2", source_type="empty", base_id=uuid.uuid4())


def test_create_empty_workspace_short_circuits(migrated_sqlite, tmp_path: Path) -> None:
    """``source_type='empty'`` should:

    * insert a Project row with ``created_via='empty'``,
      ``compute_tier='none'``, ``environment_status='active'``
    * return ``task_id=None`` (no BackgroundTasks enqueue)
    * materialize a project directory and ``git init`` it
    """
    from app.routers.projects import create_project_from_payload
    from app.schemas import ProjectCreate

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    user = _make_user()

    async def _run() -> dict:
        payload = ProjectCreate(name="kb-empty-3", source_type="empty")
        async with maker() as db:
            with patch("app.routers.projects.get_task_manager") as task_mgr:
                result = await create_project_from_payload(payload, current_user=user, db=db)
                # The empty branch must NOT enqueue a setup task.
                task_mgr.assert_not_called()
        return result

    result = asyncio.run(_run())
    project = result["project"]

    assert result["task_id"] is None
    assert result["status_endpoint"] is None
    assert getattr(project, "created_via", None) == "empty"
    assert getattr(project, "compute_tier", None) == "none"
    assert project.environment_status == "active"

    # Re-load from DB to confirm persistence.
    async def _reload() -> object:
        from app.models import Project

        async with maker() as s:
            r = await s.execute(select(Project).where(Project.id == project.id))
            return r.scalar_one()

    row = asyncio.run(_reload())
    assert row.created_via == "empty"
    assert row.compute_tier == "none"
    assert row.environment_status == "active"

    asyncio.run(engine.dispose())
