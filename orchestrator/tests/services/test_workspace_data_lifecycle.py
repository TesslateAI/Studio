"""Tests for Group D: key lifecycle hardening.

Three orthogonal changes:

* ``revoke_data_key`` now soft-revokes (flip ``is_active=False``) instead
  of hard-deleting, so the audit trail (``key_prefix`` + ``last_used_at``
  history) survives for forensics.
* ``resolve_data_key`` debounces the ``last_used_at`` write through a
  short Redis SET-NX-EX window so a burst of requests doesn't serialise
  through one Postgres write per call.
* ``_build_env_map`` refuses to spread a ``wsk_svc_*`` key under
  ``VITE_*`` / ``NEXT_PUBLIC_*`` prefixes — defense-in-depth against the
  agent accidentally baking a project-root secret into a browser bundle.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-lifecycle.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    engine = create_async_engine(url, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _now(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))

    yield async_sessionmaker(engine, expire_on_commit=False)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. Soft-revoke
# ---------------------------------------------------------------------------
async def test_revoke_soft_deletes_and_keeps_audit_row(maker) -> None:
    """Revoke flips ``is_active=False`` but leaves the row + audit fields."""
    from app.models_workspace_data import WorkspaceDataKey
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        key, raw = await wd.create_data_key(db, pid, "soft-rev", "anon")
        kid = key.id
        prefix = key.key_prefix

        assert await wd.revoke_data_key(db, pid, kid) is True
        # Row must still exist with is_active=False (so audit / list-keys still see it).
        row = (
            await db.execute(select(WorkspaceDataKey).where(WorkspaceDataKey.id == kid))
        ).scalar_one_or_none()
        assert row is not None, "soft-revoke must NOT hard-delete the row"
        assert row.is_active is False
        assert row.key_prefix == prefix  # audit metadata preserved

        # Already-revoked → False (idempotent, no double-write).
        assert await wd.revoke_data_key(db, pid, kid) is False

        # Authentication stops immediately.
        assert await wd.resolve_data_key(db, raw) is None


# ---------------------------------------------------------------------------
# 2. Debounced ``last_used_at``
# ---------------------------------------------------------------------------
async def test_last_used_at_debounced_when_redis_says_no(maker) -> None:
    """When Redis SET-NX-EX returns 'not first in window', no UPDATE happens."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        key, raw = await wd.create_data_key(db, pid, "debounce", "anon")
        assert key.last_used_at is None

        # Force the debounce gate closed — simulates "another request just
        # stamped within the window".
        with patch(
            "app.services.workspace_data.keys._should_stamp_last_used",
            new=AsyncMock(return_value=False),
        ):
            resolved = await wd.resolve_data_key(db, raw)
        assert resolved is not None
        # last_used_at must remain None — the debounce skipped the write.
        async with maker() as db2:
            from app.models_workspace_data import WorkspaceDataKey

            row = (
                await db2.execute(select(WorkspaceDataKey).where(WorkspaceDataKey.id == key.id))
            ).scalar_one()
            assert row.last_used_at is None


async def test_last_used_at_stamped_when_gate_open(maker) -> None:
    """When Redis is unavailable / window open, the stamp still happens
    (best-effort write, never blocks the response)."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        key, raw = await wd.create_data_key(db, pid, "stamp", "anon")
        with patch(
            "app.services.workspace_data.keys._should_stamp_last_used",
            new=AsyncMock(return_value=True),
        ):
            resolved = await wd.resolve_data_key(db, raw)
        assert resolved is not None
        async with maker() as db2:
            from app.models_workspace_data import WorkspaceDataKey

            row = (
                await db2.execute(select(WorkspaceDataKey).where(WorkspaceDataKey.id == key.id))
            ).scalar_one()
            assert row.last_used_at is not None


# ---------------------------------------------------------------------------
# 3. Service-key prefix guard in env builder
# ---------------------------------------------------------------------------
def test_env_map_excludes_browser_prefixes_for_service_key() -> None:
    """A ``wsk_svc_*`` key must NOT land under VITE_* / NEXT_PUBLIC_* — those
    are inlined into the deployed bundle by the build."""
    from app.services.workspace_data_env import _build_env_map

    out = _build_env_map("https://your-domain.com/api/data/v1", "wsk_svc_aaaaaaaabbbbccccdddd")
    # URL is non-secret → present on every prefix.
    for prefix in ("OPENSAIL", "VITE_OPENSAIL", "NEXT_PUBLIC_OPENSAIL"):
        assert f"{prefix}_DATA_API_URL" in out
        assert f"{prefix}_DATA_URL" in out
    # KEY only on the server-side prefix.
    assert out["OPENSAIL_DATA_KEY"] == "wsk_svc_aaaaaaaabbbbccccdddd"
    assert "VITE_OPENSAIL_DATA_KEY" not in out
    assert "NEXT_PUBLIC_OPENSAIL_DATA_KEY" not in out


def test_env_map_spreads_anon_key_to_all_prefixes() -> None:
    """Anon keys are browser-safe — full spread is correct."""
    from app.services.workspace_data_env import _build_env_map

    out = _build_env_map("https://your-domain.com/api/data/v1", "wsk_anon_aaaaaaaabbbbccccdddd")
    for prefix in ("OPENSAIL", "VITE_OPENSAIL", "NEXT_PUBLIC_OPENSAIL"):
        assert out[f"{prefix}_DATA_KEY"] == "wsk_anon_aaaaaaaabbbbccccdddd"


def test_env_map_url_only_when_key_none() -> None:
    """No-key path emits URLs only, on every prefix (unchanged from v1)."""
    from app.services.workspace_data_env import _build_env_map

    out = _build_env_map("https://your-domain.com/api/data/v1", None)
    assert all("DATA_KEY" not in k for k in out)
    assert "OPENSAIL_DATA_API_URL" in out
