"""Verify migration 0051 creates directories + agent_task_directories tables."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config


@pytest.fixture
def sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "migration.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    yield str(db_path)
    get_settings.cache_clear()


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


def test_0051_creates_directory_tables(sqlite_db: str) -> None:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)

    conn = sqlite3.connect(sqlite_db)
    try:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "directories" in tables
        assert "agent_task_directories" in tables

        # Round-trip a directory + join row (FKs off by default in sqlite).
        user_id = str(uuid4())
        directory_id = str(uuid4())
        ticket_id = str(uuid4())
        project_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO directories (id, user_id, path, runtime, git_root, created_at)"
            " VALUES (?, ?, '/tmp/proj', 'local', '/tmp/proj', ?)",
            (directory_id, user_id, now),
        )
        conn.execute(
            "INSERT INTO agent_tasks (id, ref_id, project_id, status, created_at)"
            " VALUES (?, 'TSK-0001', ?, 'queued', ?)",
            (ticket_id, project_id, now),
        )
        conn.execute(
            "INSERT INTO agent_task_directories (ticket_id, directory_id) VALUES (?, ?)",
            (ticket_id, directory_id),
        )
        conn.commit()

        joined = conn.execute(
            "SELECT d.path FROM directories d"
            " JOIN agent_task_directories j ON j.directory_id = d.id"
            " WHERE j.ticket_id=?",
            (ticket_id,),
        ).fetchone()
        assert joined == ("/tmp/proj",)
    finally:
        conn.close()
