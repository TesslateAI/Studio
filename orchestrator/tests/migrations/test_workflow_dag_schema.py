"""Verify alembic 0083 adds workflow/DAG prep columns to automation_actions.

The Phase 5 migration is schema-only (no execution logic). This test
exercises the SQLite path used by the desktop sidecar so we catch
``op.batch_alter_table`` regressions before they hit a real desktop
build.

Coverage:

* ``upgrade head`` adds ``parent_action_id`` + ``branch_condition`` to
  ``automation_actions``.
* The CHECK on ``action_type`` now accepts ``'workflow.run'`` (raw insert
  via sqlite3 succeeds where it previously raised ``IntegrityError``).
* A child row referencing a parent via ``parent_action_id`` round-trips
  through INSERT + SELECT.
* Downgrading one revision (``0083`` → ``0082``) drops both columns and
  restores the narrower CHECK.
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
    db_path = tmp_path / "workflow_dag.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    # Force settings re-read so the sqlite URL takes effect for the
    # alembic env.py.
    from app.config import get_settings

    get_settings.cache_clear()
    yield str(db_path)
    get_settings.cache_clear()


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


def _seed_min_definition(conn: sqlite3.Connection) -> tuple[str, str]:
    """Insert the minimal owner_user + automation_definition row needed to
    satisfy the FK on automation_actions.automation_id.

    Returns ``(user_id, automation_id)``.
    """
    user_id = str(uuid4())
    auto_id = str(uuid4())

    conn.execute(
        """
        INSERT INTO users (
            id, email, hashed_password, is_active, is_superuser, is_verified,
            name, username, slug, created_at, updated_at
        ) VALUES (?, ?, 'x', 1, 0, 1, 'M', 'mig', ?, datetime('now'), datetime('now'))
        """,
        (user_id, f"mig-{user_id[:8]}@example.com", f"mig-{user_id[:8]}"),
    )
    conn.execute(
        """
        INSERT INTO automation_definitions (
            id, name, owner_user_id, workspace_scope, contract,
            max_compute_tier, depth, is_active, created_at, updated_at
        ) VALUES (?, 'mig-test', ?, 'none', '{"x":1}', 0, 0, 1,
                  datetime('now'), datetime('now'))
        """,
        (auto_id, user_id),
    )
    conn.commit()
    return user_id, auto_id


def test_0083_upgrade_adds_dag_columns(sqlite_db: str) -> None:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original_cwd = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original_cwd)

    conn = sqlite3.connect(sqlite_db)
    try:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info('automation_actions')"
        )}
        assert "parent_action_id" in cols
        assert "branch_condition" in cols

        _, auto_id = _seed_min_definition(conn)

        # Insert a parent action; should succeed even with action_type
        # 'workflow.run' (the new value).
        parent_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO automation_actions (
                id, automation_id, ordinal, action_type, config, created_at
            ) VALUES (?, ?, 0, 'workflow.run', '{}', datetime('now'))
            """,
            (parent_id, auto_id),
        )
        conn.commit()

        # Insert a child whose parent_action_id points at the row above.
        child_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO automation_actions (
                id, automation_id, ordinal, action_type, config,
                parent_action_id, branch_condition, created_at
            ) VALUES (?, ?, 1, 'agent.run', '{}', ?, ?, datetime('now'))
            """,
            (child_id, auto_id, parent_id, '{"op":"==","left":"$x","right":1}'),
        )
        conn.commit()

        row = conn.execute(
            "SELECT parent_action_id, branch_condition, action_type "
            "FROM automation_actions WHERE id = ?",
            (child_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == parent_id
        assert row[1] == '{"op":"==","left":"$x","right":1}'
        assert row[2] == "agent.run"

        # Reverse lookup uses the new index — exercise the query shape the
        # Phase 6 dispatcher will run.
        children = conn.execute(
            "SELECT id FROM automation_actions WHERE parent_action_id = ?",
            (parent_id,),
        ).fetchall()
        assert [r[0] for r in children] == [child_id]
    finally:
        conn.close()


def test_0083_downgrade_drops_dag_columns(sqlite_db: str) -> None:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original_cwd = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
        # Down to 0082_automation_grants so 0083 is fully reverted —
        # ``head`` may sit on a later revision (e.g. 0084_contract_templates)
        # and a relative ``-1`` would only undo that.
        command.downgrade(_alembic_cfg(), "0082_automation_grants")
    finally:
        os.chdir(original_cwd)

    conn = sqlite3.connect(sqlite_db)
    try:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info('automation_actions')"
        )}
        assert "parent_action_id" not in cols
        assert "branch_condition" not in cols

        # 'workflow.run' must now be rejected by the narrower CHECK.
        _, auto_id = _seed_min_definition(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO automation_actions (
                    id, automation_id, ordinal, action_type, config, created_at
                ) VALUES (?, ?, 0, 'workflow.run', '{}', datetime('now'))
                """,
                (str(uuid4()), auto_id),
            )
            conn.commit()
    finally:
        conn.close()
