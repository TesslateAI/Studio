"""Verify migration 0049 adds runtime/source_path/sync_enabled to projects.

Runs alembic programmatically against a fresh SQLite DB, then inserts and
selects a project row to prove the new columns are wired up.
"""

from __future__ import annotations

import os
import sqlite3
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

    # Force settings re-read.
    from app.config import get_settings

    get_settings.cache_clear()

    yield str(db_path)

    get_settings.cache_clear()


def _alembic_cfg() -> Config:
    # tests/migrations/test_*.py → go up two levels to orchestrator/.
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    # Point alembic at the canonical script dir regardless of cwd.
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


def test_0049_upgrade_adds_columns(sqlite_db: str) -> None:
    original_cwd = os.getcwd()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original_cwd)

    # Inspect the schema with a sync sqlite3 connection (alembic ran async).
    conn = sqlite3.connect(sqlite_db)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info('projects')")}
        assert "runtime" in cols
        assert "source_path" in cols
        assert "sync_enabled" in cols

        # Insert a minimal project row with runtime='local'.
        project_id = str(uuid4())
        owner_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO projects (
                id, owner_id, name, slug,
                runtime, source_path, sync_enabled,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                project_id,
                owner_id,
                "migration-test",
                "migration-test",
                "local",
                "/tmp/fake/source",
                0,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT runtime, source_path, sync_enabled FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        assert row == ("local", "/tmp/fake/source", 0)
    finally:
        conn.close()
