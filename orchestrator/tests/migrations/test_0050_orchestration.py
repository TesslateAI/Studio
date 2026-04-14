"""Verify migration 0050 creates agent_tasks, agent_budgets, projects.mission."""

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


def test_0050_creates_tables_and_column(sqlite_db: str) -> None:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)

    conn = sqlite3.connect(sqlite_db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "agent_tasks" in tables
        assert "agent_budgets" in tables

        cols = {r[1] for r in conn.execute("PRAGMA table_info('projects')")}
        assert "mission" in cols

        # Round-trip a ticket + budget row (FKs are off in sqlite by default).
        project_id = str(uuid4())
        ticket_id = str(uuid4())
        budget_id = str(uuid4())
        agent_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO agent_tasks (id, ref_id, project_id, status, created_at)"
            " VALUES (?, 'TSK-0001', ?, 'queued', ?)",
            (ticket_id, project_id, now),
        )
        conn.execute(
            "INSERT INTO agent_budgets (id, agent_id, project_id, monthly_limit_usd, spent_usd, reset_at)"
            " VALUES (?, ?, NULL, ?, ?, ?)",
            (budget_id, agent_id, 100, 0, now),
        )
        conn.commit()

        ticket_row = conn.execute(
            "SELECT ref_id, status FROM agent_tasks WHERE id=?", (ticket_id,)
        ).fetchone()
        assert ticket_row == ("TSK-0001", "queued")

        budget_row = conn.execute(
            "SELECT monthly_limit_usd, spent_usd FROM agent_budgets WHERE id=?", (budget_id,)
        ).fetchone()
        assert budget_row[0] == 100 and budget_row[1] == 0
    finally:
        conn.close()
