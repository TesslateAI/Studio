"""Tests for the install dedupe gate.

Two layers:

* Fast-path: ``installer.install_app`` does a SELECT against
  ``app_instances`` filtered by (installer_user_id, app_id,
  state='installed'). On Postgres an advisory transaction lock
  ``pg_advisory_xact_lock`` keyed on the same tuple serializes concurrent
  installs so the second sees the first's row.
* Hard gate: alembic 0085's partial UNIQUE on
  ``(installer_user_id, app_id) WHERE state='installed'`` (mirrored on
  the model so SQLite test fixtures share the constraint). The
  ``IntegrityError`` translation in ``install_app`` re-emits as
  ``AlreadyInstalledError`` regardless of whether the project-side or
  user-side index fired.

These tests pin the SELECT-side dedupe (fast-path) and the index-side
dedupe (hard gate). The advisory lock itself is a Postgres-only
optimization and isn't exercised by SQLite-backed unit tests; its
presence is asserted via static inspection of the install_app source.
"""

from __future__ import annotations

import inspect
import json as _json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import models, models_automations  # noqa: F401  -- register tables
from app.database import Base
from app.services.apps import installer
from app.services.apps.installer import (
    AlreadyInstalledError,
    install_app,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _runtime_manifest(slug: str) -> dict[str, Any]:
    return {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": f"com.example.{slug}",
            "name": f"App {slug}",
            "slug": slug,
            "version": "1.0.0",
        },
        "runtime": {
            "tenancy_model": "per_install",
            "state_model": "per_install_volume",
            "scaling": {"min_replicas": 0, "max_replicas": 1},
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {"model": "free", "rate_percent": 0, "price_usd": 0},
        },
    }


_DEFAULT_BUNDLE_CONFIG_JSON = _json.dumps(
    {
        "primaryApp": "primary",
        "apps": {
            "primary": {
                "directory": "/app",
                "start": "node index.js",
                "port": 3000,
            }
        },
        "infrastructure": {},
        "connections": [],
    }
)


class _StubOrchestrator:
    async def read_file(self, **kwargs: Any) -> str | None:
        if kwargs.get("file_path") == ".tesslate/config.json":
            return _DEFAULT_BUNDLE_CONFIG_JSON
        return None


class _FakeHubClient:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []

    async def create_volume_from_bundle(
        self,
        *,
        bundle_hash: str,
        hint_node: str | None = None,
        timeout: float = 600.0,
    ) -> tuple[str, str]:
        self.create_calls.append({"bundle_hash": bundle_hash})
        return f"vol-{uuid.uuid4().hex[:8]}", "node-test"


@pytest.fixture(autouse=True)
def _patch_install_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub orchestrator so the install path can read .tesslate/config.json."""
    import app.services.orchestration as _orchestration

    monkeypatch.setattr(
        _orchestration, "get_orchestrator", lambda *a, **kw: _StubOrchestrator()
    )


async def _seed(db: AsyncSession, slug: str):
    user_id = uuid.uuid4()
    user = models.User(
        id=user_id,
        email=f"u-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        name="X",
        username=f"user-{user_id.hex[:10]}",
        slug=f"user-{user_id.hex[:10]}",
    )
    db.add(user)
    team = models.Team(
        id=uuid.uuid4(),
        slug=f"team-{user_id.hex[:10]}",
        name="T",
        is_personal=True,
        created_by_id=user_id,
    )
    db.add(team)
    await db.flush()
    manifest = _runtime_manifest(slug)
    app_row = models.MarketplaceApp(
        id=uuid.uuid4(),
        slug=slug,
        name=manifest["app"]["name"],
        creator_user_id=user_id,
        state="draft",
        visibility="public",
    )
    db.add(app_row)
    await db.flush()
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app_row.id,
        version=manifest["app"]["version"],
        manifest_schema_version=manifest["manifest_schema_version"],
        manifest_json=manifest,
        manifest_hash="sha256:" + ("a" * 64),
        bundle_hash="sha256:" + ("b" * 64),
        feature_set_hash="fs:test",
        required_features=[],
        approval_state="stage1_approved",
    )
    db.add(av)
    await db.flush()
    return user, team, app_row, av


def _consent() -> dict[str, Any]:
    return {
        "ai_compute": {"payer": "installer"},
        "general_compute": {"payer": "installer"},
        "platform_fee": {"model": "free"},
    }


# ---------------------------------------------------------------------------
# Fast-path: SELECT-side dedupe rejects the second install cleanly.
# ---------------------------------------------------------------------------


async def test_second_install_for_same_user_app_raises_already_installed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user, team, _app, av = await _seed(db, "dedupe-fast-path")
    hub = _FakeHubClient()

    first = await install_app(
        db,
        installer_user_id=user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team.id,
    )

    with pytest.raises(AlreadyInstalledError) as exc_info:
        await install_app(
            db,
            installer_user_id=user.id,
            app_version_id=av.id,
            hub_client=hub,
            wallet_mix_consent=_consent(),
            mcp_consents=[],
            team_id=team.id,
        )

    # The error carries the existing instance id so the UI can surface a
    # "you already have this installed — open it?" affordance.
    assert exc_info.value.app_instance_id == first.app_instance_id
    # Hub was only called once — second install bailed before any side effect.
    assert len(hub.create_calls) == 1


# ---------------------------------------------------------------------------
# Hard gate: partial UNIQUE rejects rows that slipped past the SELECT.
# ---------------------------------------------------------------------------


async def test_partial_unique_index_rejects_second_installed_row(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a second ``state='installed'`` row for the same (user, app) is
    inserted directly (bypassing install_app's SELECT dedupe), the partial
    UNIQUE index from alembic 0085 must reject it.
    """
    from sqlalchemy.exc import IntegrityError

    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user, team, app_row, av = await _seed(db, "dedupe-hard-gate")
    hub = _FakeHubClient()

    first = await install_app(
        db,
        installer_user_id=user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team.id,
    )
    # Commit the first install so the rollback that follows the rogue
    # insert can't undo it. ``install_app`` doesn't commit — the caller
    # owns the transaction; tests stand in for that caller.
    await db.commit()

    project_id = uuid.uuid4()
    project = models.Project(
        id=project_id,
        name="Decoy",
        slug=f"decoy-{project_id.hex[:6]}",
        owner_id=user.id,
        team_id=team.id,
        visibility="team",
        project_kind=models.PROJECT_KIND_APP_RUNTIME,
        volume_id=f"vol-{project_id.hex[:8]}",
    )
    db.add(project)
    await db.flush()
    rogue = models_automations.AppInstance(
        id=uuid.uuid4(),
        app_id=app_row.id,
        app_version_id=av.id,
        installer_user_id=user.id,
        project_id=project_id,
        state="installed",
    )
    db.add(rogue)
    with pytest.raises(IntegrityError) as exc_info:
        await db.flush()
    # SQLite + Postgres surface the violation differently: SQLite names
    # the columns failing in the constraint clause (we look in the
    # leading ``UNIQUE constraint failed: ...`` line so the trailing SQL
    # echo doesn't muddy the match). Postgres names the index. Either
    # form is acceptable; what we want to know is "the new partial
    # UNIQUE on (installer_user_id, app_id) fired."
    first_line = str(exc_info.value).splitlines()[0].lower()
    assert (
        "uq_app_instances_user_app_installed" in first_line
        or (
            "unique constraint failed" in first_line
            and "installer_user_id" in first_line
            and "app_id" in first_line
        )
    ), f"unexpected integrity error first line: {first_line!r}"
    # Reference ``first`` so static analysis doesn't flag the unused
    # binding — the integrity error is the load-bearing assertion.
    assert first.app_instance_id is not None


# ---------------------------------------------------------------------------
# Uninstall releases the constraint slot — the user can re-install.
# ---------------------------------------------------------------------------


async def test_reinstall_after_uninstall_succeeds(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The partial UNIQUE only fires for ``state='installed'``, so an
    uninstalled row in the same (user, app) shouldn't block reinstall.
    """
    from datetime import UTC, datetime

    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user, team, _app, av = await _seed(db, "dedupe-reinstall")
    hub = _FakeHubClient()

    first = await install_app(
        db,
        installer_user_id=user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team.id,
    )

    inst_row = await db.get(models_automations.AppInstance, first.app_instance_id)
    assert inst_row is not None
    inst_row.state = "uninstalled"
    inst_row.uninstalled_at = datetime.now(UTC)
    inst_row.project_id = None
    await db.commit()

    second = await install_app(
        db,
        installer_user_id=user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team.id,
    )
    assert second.app_instance_id != first.app_instance_id


# ---------------------------------------------------------------------------
# Static check: the advisory-lock branch is wired up.
# ---------------------------------------------------------------------------


def test_install_app_uses_postgres_advisory_lock() -> None:
    """The advisory lock is a Postgres-only fast-path; SQLite test
    fixtures don't exercise it. Assert that the source carries the
    ``pg_advisory_xact_lock`` call so a future refactor can't silently
    drop the serialization without breaking this test.
    """
    src = inspect.getsource(install_app)
    assert "pg_advisory_xact_lock" in src
    assert "hashtextextended" in src
    assert "postgresql" in src
