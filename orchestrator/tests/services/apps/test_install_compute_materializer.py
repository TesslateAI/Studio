"""Tests for ``install_compute_materializer.materialize_compute_from_volume``.

The 2026-05 manifest dropped ``compute.containers[]``. Container layout for
an installed app now comes from ``.tesslate/config.json`` on the materialized
volume — the bundle CAS already snapshots it from the source project. The
materializer reads that config via the orchestrator file API and writes
``Container`` + ``ContainerConnection`` rows in the install transaction.

These tests pin the contract:

* Container rows are created from ``config.apps`` (base) and
  ``config.infrastructure`` (service).
* ``primaryApp`` is honored; if absent, the first inserted base container
  becomes primary.
* ``ContainerConnection`` rows mirror ``config.connections``; unknown names
  are skipped with a warning rather than aborting the install.
* ``BundleConfigMissing`` is raised when ``read_file`` returns falsy or the
  parsed config is empty — the install path translates these to a clean
  ``IncompatibleAppError``.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models, models_automations  # noqa: F401  -- register tables
from app.database import Base
from app.models import (
    PROJECT_KIND_APP_RUNTIME,
    Container,
    ContainerConnection,
    Project,
    Team,
    User,
)
from app.services.apps.install_compute_materializer import (
    BundleConfigMissing,
    materialize_compute_from_volume,
)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def runtime_project(db: AsyncSession) -> tuple[Project, uuid.UUID]:
    """A minimal app_runtime Project + its installer user, ready for materialization."""
    user_id = uuid.uuid4()
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            name="Installer",
            username=f"user-{user_id.hex[:10]}",
            slug=f"user-{user_id.hex[:10]}",
        )
    )
    team_id = uuid.uuid4()
    db.add(
        Team(
            id=team_id,
            slug=f"team-{team_id.hex[:10]}",
            name="Inst Team",
            is_personal=True,
            created_by_id=user_id,
        )
    )
    await db.flush()

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name="App (installed)",
        slug=f"app-inst-{project_id.hex[:6]}",
        owner_id=user_id,
        team_id=team_id,
        visibility="team",
        project_kind=PROJECT_KIND_APP_RUNTIME,
        volume_id=f"vol-{project_id.hex[:8]}",
    )
    db.add(project)
    await db.flush()
    return project, user_id


class _FakeOrchestrator:
    """Minimal stand-in for ``BaseOrchestrator`` capturing read_file calls."""

    def __init__(self, payloads: dict[str, str | None]) -> None:
        self._payloads = payloads
        self.calls: list[dict[str, Any]] = []

    async def read_file(self, **kwargs: Any) -> str | None:
        self.calls.append(kwargs)
        return self._payloads.get(kwargs.get("file_path", ""))


def _patch_orchestrator(monkeypatch: pytest.MonkeyPatch, fake: _FakeOrchestrator) -> None:
    import app.services.orchestration as orchestration_module

    monkeypatch.setattr(
        orchestration_module, "get_orchestrator", lambda *a, **kw: fake
    )


# ---------------------------------------------------------------------------
# Happy path: apps + infrastructure + primaryApp + connections.
# ---------------------------------------------------------------------------


async def test_materializes_apps_infra_and_connections(
    db: AsyncSession,
    runtime_project: tuple[Project, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, installer_user_id = runtime_project

    config_payload = json.dumps(
        {
            "primaryApp": "frontend",
            "apps": {
                "frontend": {
                    "name": "frontend",
                    "framework": "vite",
                    "directory": "/app",
                    "start": "npm run dev",
                    "port": 5173,
                    "env": {"PUBLIC_API": "http://api"},
                },
                "backend": {
                    "name": "backend",
                    "directory": "/app/api",
                    "start": "uvicorn main:app",
                    "port": 8000,
                },
            },
            "infrastructure": {
                "db": {
                    "type": "container",
                    "image": "postgres:16",
                    "port": 5432,
                    "env": {"POSTGRES_DB": "app"},
                }
            },
            "connections": [
                {"from": "backend", "to": "db"},
                # Unknown source — must be logged + skipped, not crash.
                {"from": "ghost", "to": "db"},
            ],
        }
    )
    fake = _FakeOrchestrator({".tesslate/config.json": config_payload})
    _patch_orchestrator(monkeypatch, fake)

    overlay = {"OPENSAIL_RUNTIME_URL": "http://opensail-runtime:8400"}
    containers_by_name, primary = await materialize_compute_from_volume(
        db,
        project=project,
        installer_user_id=installer_user_id,
        volume_id=project.volume_id,
        cache_node="node-a",
        runtime_env_overlay=overlay,
    )

    # Orchestrator was called once with the expected args.
    assert len(fake.calls) == 1, fake.calls
    call = fake.calls[0]
    assert call["file_path"] == ".tesslate/config.json"
    assert call["project_slug"] == project.slug
    assert call["volume_id"] == project.volume_id
    assert call["cache_node"] == "node-a"

    # Container rows.
    assert set(containers_by_name) == {"frontend", "backend", "db"}
    assert containers_by_name["frontend"].container_type == "base"
    assert containers_by_name["backend"].container_type == "base"
    assert containers_by_name["db"].container_type == "service"

    # Primary tracked correctly.
    assert primary is not None
    assert primary.name == "frontend"
    assert primary.is_primary is True
    assert containers_by_name["backend"].is_primary is False
    assert containers_by_name["db"].is_primary is False

    # Runtime overlay applied to base apps; manifest values preserved.
    fe_env = containers_by_name["frontend"].environment_vars or {}
    assert fe_env.get("PUBLIC_API") == "http://api"
    assert fe_env.get("OPENSAIL_RUNTIME_URL") == "http://opensail-runtime:8400"
    # Service containers (infra) do NOT get the SDK overlay — those env
    # values are app-pod concerns, not postgres concerns.
    db_env = containers_by_name["db"].environment_vars or {}
    assert "OPENSAIL_RUNTIME_URL" not in db_env
    assert db_env.get("POSTGRES_DB") == "app"

    # Connection rows: only the valid one materialized.
    conns = (
        (
            await db.execute(
                select(ContainerConnection).where(
                    ContainerConnection.project_id == project.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(conns) == 1
    backend = containers_by_name["backend"]
    pg = containers_by_name["db"]
    assert conns[0].source_container_id == backend.id
    assert conns[0].target_container_id == pg.id


# ---------------------------------------------------------------------------
# Fallback: no primaryApp → first base container wins.
# ---------------------------------------------------------------------------


async def test_first_base_container_is_primary_when_primaryapp_missing(
    db: AsyncSession,
    runtime_project: tuple[Project, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, installer_user_id = runtime_project
    payload = json.dumps(
        {
            "apps": {
                "alpha": {"directory": "/a", "start": "node a.js", "port": 3000},
                "beta": {"directory": "/b", "start": "node b.js", "port": 3001},
            },
            "infrastructure": {},
            "connections": [],
        }
    )
    fake = _FakeOrchestrator({".tesslate/config.json": payload})
    _patch_orchestrator(monkeypatch, fake)

    containers, primary = await materialize_compute_from_volume(
        db,
        project=project,
        installer_user_id=installer_user_id,
        volume_id=project.volume_id,
        cache_node=None,
    )

    assert primary is not None
    assert primary.name == "alpha"
    assert containers["alpha"].is_primary is True
    assert containers["beta"].is_primary is False


# ---------------------------------------------------------------------------
# Failure paths: missing or empty config.
# ---------------------------------------------------------------------------


async def test_raises_bundle_config_missing_when_read_file_empty(
    db: AsyncSession,
    runtime_project: tuple[Project, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, installer_user_id = runtime_project
    fake = _FakeOrchestrator({".tesslate/config.json": None})
    _patch_orchestrator(monkeypatch, fake)

    with pytest.raises(BundleConfigMissing):
        await materialize_compute_from_volume(
            db,
            project=project,
            installer_user_id=installer_user_id,
            volume_id=project.volume_id,
            cache_node=None,
        )

    # No Container rows leaked into the install transaction.
    rows = (
        (await db.execute(select(Container).where(Container.project_id == project.id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_raises_bundle_config_missing_when_config_has_no_apps(
    db: AsyncSession,
    runtime_project: tuple[Project, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bundle whose ``.tesslate/config.json`` defines neither apps nor
    infrastructure can't run — fail closed rather than create a project
    with zero containers (which is the bug we just fixed)."""
    project, installer_user_id = runtime_project
    payload = json.dumps({"apps": {}, "infrastructure": {}, "connections": []})
    fake = _FakeOrchestrator({".tesslate/config.json": payload})
    _patch_orchestrator(monkeypatch, fake)

    with pytest.raises(BundleConfigMissing):
        await materialize_compute_from_volume(
            db,
            project=project,
            installer_user_id=installer_user_id,
            volume_id=project.volume_id,
            cache_node=None,
        )


async def test_unknown_connection_names_skipped_with_warning(
    db: AsyncSession,
    runtime_project: tuple[Project, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project, installer_user_id = runtime_project
    payload = json.dumps(
        {
            "apps": {
                "frontend": {"directory": "/app", "start": "npm start", "port": 3000},
            },
            "infrastructure": {},
            "connections": [
                {"from": "frontend", "to": "ghost-service"},
            ],
        }
    )
    fake = _FakeOrchestrator({".tesslate/config.json": payload})
    _patch_orchestrator(monkeypatch, fake)

    with caplog.at_level(logging.WARNING, logger="app.services.apps.install_compute_materializer"):
        await materialize_compute_from_volume(
            db,
            project=project,
            installer_user_id=installer_user_id,
            volume_id=project.volume_id,
            cache_node=None,
        )

    # No connection rows.
    conns = (
        (
            await db.execute(
                select(ContainerConnection).where(
                    ContainerConnection.project_id == project.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert conns == []
    # Warning emitted naming the bad target.
    assert any(
        "ghost-service" in rec.getMessage() and "skipping connection" in rec.getMessage()
        for rec in caplog.records
    ), [r.getMessage() for r in caplog.records]
