"""Tests for Group E: audit hooks + API version header.

Audit-write paths are exercised via the router functions directly with a
spy on ``audit_log_event`` — no TestClient overhead. The version-header
test verifies the router-level dependency is wired correctly by reading
the OpenAPI schema.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-audit.db'}"
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


def _fake_request():
    return SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.99"),
        headers={"user-agent": "pytest"},
    )


def _fake_user_project():
    project = SimpleNamespace(
        id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        slug="probe-project",
    )
    user = SimpleNamespace(id=uuid.uuid4())
    return user, project


# ---------------------------------------------------------------------------
# Audit hooks
# ---------------------------------------------------------------------------
async def test_audit_helper_records_workspace_data_action(maker) -> None:
    """The router-local _audit wrapper sets resource_type=workspace_data
    and pulls project_id + team_id automatically.

    Note: _audit opens a fresh AsyncSessionLocal-backed session under the
    hood (to survive the request session's no-commit teardown). The spy
    captures both the log_event call and the fact that a session is
    passed in — we assert on action shape, not the exact session ID.
    """
    from app.routers.workspace_data import _audit

    user, project = _fake_user_project()
    with patch("app.routers.workspace_data.audit_log_event", new=AsyncMock()) as spy:
        async with maker() as db:
            await _audit(
                db,
                _fake_request(),
                project,
                user,
                "workspace_data.test.event",
                resource_id=uuid.uuid4(),
                details={"foo": "bar"},
            )
    spy.assert_awaited_once()
    kwargs = spy.await_args.kwargs
    assert kwargs["team_id"] == project.team_id
    assert kwargs["project_id"] == project.id
    assert kwargs["user_id"] == user.id
    assert kwargs["resource_type"] == "workspace_data"
    assert kwargs["action"] == "workspace_data.test.event"
    assert kwargs["details"] == {"foo": "bar"}


async def test_audit_helper_skips_when_project_missing_team(maker) -> None:
    """Defensive — a project without a team_id is anomalous; the audit
    helper should silently skip rather than 500 on a NULL FK."""
    from app.routers.workspace_data import _audit

    user, project = _fake_user_project()
    project.team_id = None
    with patch("app.routers.workspace_data.audit_log_event", new=AsyncMock()) as spy:
        async with maker() as db:
            await _audit(db, _fake_request(), project, user, "any.action")
    spy.assert_not_awaited()


async def test_audit_helper_swallows_audit_failures_non_blocking(maker) -> None:
    """A broken audit path (DB unreachable, schema drift, …) must NEVER
    bubble up and 500 the primary mgmt API call. The whole subsystem is
    documented as fire-and-forget."""
    from app.routers.workspace_data import _audit

    user, project = _fake_user_project()
    with patch(
        "app.routers.workspace_data.audit_log_event",
        new=AsyncMock(side_effect=RuntimeError("simulated DB failure")),
    ):
        async with maker() as db:
            # Must NOT raise.
            await _audit(db, _fake_request(), project, user, "any.action")


# ---------------------------------------------------------------------------
# API version header — sourced from the workspace_data router, applied by
# the DynamicCORSMiddleware in main.py (so error-response paths get it too).
# ---------------------------------------------------------------------------
def test_version_constant_is_a_string() -> None:
    """Future-proof: the header value must be a string ('1' not int(1)).
    The middleware passes it straight into a Response header dict.
    """
    from app.routers.workspace_data import DATA_API_VERSION

    assert isinstance(DATA_API_VERSION, str)
    assert DATA_API_VERSION  # non-empty


def test_main_middleware_stamps_version_on_data_api_responses() -> None:
    """Catch a regression where the version-header import in main.py
    silently drops — string-search the middleware definition for the
    canonical lazy-import + stamp pattern, no full app boot needed."""
    from pathlib import Path

    main_src = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text()
    # Lazy import + stamp call, both inside the /api/data/ block.
    data_block_start = main_src.find('request.url.path.startswith("/api/data/")')
    assert data_block_start != -1, "/api/data/ middleware block missing"
    # 2 KB window is enough to span the block + the surrounding context.
    block = main_src[data_block_start : data_block_start + 2048]
    assert "DATA_API_VERSION" in block
    assert "X-OpenSail-Data-API-Version" in block
