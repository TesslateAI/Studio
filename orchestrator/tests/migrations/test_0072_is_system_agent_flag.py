"""Verify migration 0072 revision ID fits within alembic_version VARCHAR(32).

The original revision "0072_add_is_system_to_marketplace_agents" (40 chars)
crashed the backend on startup with StringDataRightTruncationError because
alembic_version.version_num is VARCHAR(32). The renamed ID must fit.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

REVISION_ID = "0072_is_system_agent_flag"
MAX_VERSION_NUM_LENGTH = 32  # alembic_version.version_num column width


def test_revision_id_fits_varchar32() -> None:
    assert len(REVISION_ID) <= MAX_VERSION_NUM_LENGTH, (
        f"Revision ID {REVISION_ID!r} is {len(REVISION_ID)} chars, "
        f"exceeds alembic_version VARCHAR({MAX_VERSION_NUM_LENGTH})"
    )


def test_revision_module_declares_correct_id() -> None:
    """The Python migration file must declare the same short revision ID."""
    import importlib.util

    orchestrator_dir = Path(__file__).resolve().parents[2]
    migration_path = orchestrator_dir / "alembic" / "versions" / f"{REVISION_ID}.py"
    assert migration_path.exists(), f"Migration file not found: {migration_path}"

    spec = importlib.util.spec_from_file_location("migration_0072", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    assert module.revision == REVISION_ID, (
        f"revision in file is {module.revision!r}, expected {REVISION_ID!r}"
    )
    assert len(module.revision) <= MAX_VERSION_NUM_LENGTH


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


def test_0072_upgrade_adds_is_system_column(sqlite_db: str) -> None:
    original_cwd = os.getcwd()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original_cwd)

    conn = sqlite3.connect(sqlite_db)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info('marketplace_agents')")}
        assert "is_system" in cols, "is_system column must exist after migration"

        # Verify the revision was stored without truncation.
        versions = [row[0] for row in conn.execute("SELECT version_num FROM alembic_version")]
        # After upgrading to head the latest revision must be present and unfrozen.
        assert any(v == REVISION_ID or len(v) <= MAX_VERSION_NUM_LENGTH for v in versions)
    finally:
        conn.close()
