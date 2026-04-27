"""Tests for ``services.automations.wake._resolve_runtime``.

Walks the full chain ``AutomationRun → AutomationAction → AppAction →
AppInstance → AppRuntimeDeployment`` against a real SQLite database
upgraded to alembic ``head``. The resolver is the load-bearing
mechanism letting :func:`provision_for_run` operate without an explicit
``deployment_override`` — the action dispatcher passes the override
today, but background runners (cron-triggered automation runs that
target an installed app) rely on this lookup to find the deployment to
wake.

Coverage matrix:

* Happy path: full chain resolves to the install's runtime deployment.
* Automation has no ``app.invoke`` action (e.g. ``agent.run`` only) →
  returns ``None`` (no deployment to wake).
* Install row exists but ``runtime_deployment_id`` is NULL (legacy
  install predating Phase 3) → returns ``None``.
* Owner mismatch: an install owned by a DIFFERENT user must NOT be
  resolved when the automation's owner has no install of their own.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/services/automations/test_wake.py)
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "wake_resolve.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"resolve-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Resolve Tester",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_app_action(
    db, *, app_version_id: uuid.UUID, action_name: str = "do_thing"
) -> uuid.UUID:
    """Insert a minimal AppAction row pointing at a fake app_version."""
    from app.models_automations import AppAction

    action = AppAction(
        id=uuid.uuid4(),
        app_version_id=app_version_id,
        name=action_name,
        handler={"kind": "http_post", "container": "api", "path": "/do"},
    )
    db.add(action)
    await db.flush()
    return action.id


async def _seed_runtime_deployment(
    db, *, app_id: uuid.UUID, app_version_id: uuid.UUID
) -> uuid.UUID:
    """Insert a minimal AppRuntimeDeployment row."""
    from app.models_automations import AppRuntimeDeployment

    deployment = AppRuntimeDeployment(
        id=uuid.uuid4(),
        app_id=app_id,
        app_version_id=app_version_id,
        tenancy_model="per_install",
        state_model="stateless",
        namespace="proj-test",
        primary_container_id="app-test",
    )
    db.add(deployment)
    await db.flush()
    return deployment.id


async def _seed_app_install(
    db,
    *,
    installer_user_id: uuid.UUID,
    app_id: uuid.UUID,
    app_version_id: uuid.UUID,
    runtime_deployment_id: uuid.UUID | None,
) -> uuid.UUID:
    """Insert a minimal AppInstance row."""
    from app.models_automations import AppInstance

    install = AppInstance(
        id=uuid.uuid4(),
        app_id=app_id,
        app_version_id=app_version_id,
        installer_user_id=installer_user_id,
        state="installed",
        runtime_deployment_id=runtime_deployment_id,
        installed_at=datetime.now(UTC),
    )
    db.add(install)
    await db.flush()
    return install.id


async def _seed_app_and_version(
    db, *, creator_user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a MarketplaceApp + AppVersion via core insert (no relationships needed)."""
    from app.models import AppVersion, MarketplaceApp

    app_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(MarketplaceApp.__table__).values(
            id=app_id,
            slug=f"resolve-app-{suffix}",
            name=f"Resolve App {suffix}",
            creator_user_id=creator_user_id,
            state="draft",
            visibility="public",
        )
    )
    av_id = uuid.uuid4()
    await db.execute(
        core_insert(AppVersion.__table__).values(
            id=av_id,
            app_id=app_id,
            version="1.0.0",
            manifest_schema_version="2026-05",
            manifest_json={},
            manifest_hash="sha256:" + ("a" * 64),
            bundle_hash="sha256:" + ("b" * 64),
            feature_set_hash="fs:test",
            required_features=[],
            approval_state="stage1_approved",
        )
    )
    await db.flush()
    return app_id, av_id


async def _seed_run_with_app_invoke(
    db,
    *,
    owner_user_id: uuid.UUID,
    app_action_id: uuid.UUID | None,
) -> uuid.UUID:
    """Insert AutomationDefinition + AutomationAction(app.invoke) + AutomationRun."""
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
    )

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="resolve-test",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={"allowed_tools": [], "max_compute_tier": 0},
        max_compute_tier=0,
        is_active=True,
    )
    db.add(autom)
    if app_action_id is not None:
        action_row = AutomationAction(
            id=uuid.uuid4(),
            automation_id=autom.id,
            ordinal=0,
            action_type="app.invoke",
            config={},
            app_action_id=app_action_id,
        )
        db.add(action_row)
    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=autom.id,
        payload={},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=autom.id,
        event_id=evt.id,
        status="preflight",
    )
    db.add(run)
    await db.flush()
    return run.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_runtime_returns_deployment_for_full_chain(session_maker) -> None:
    """Happy path: full chain → AppRuntimeDeployment row."""
    from app.models_automations import AutomationRun
    from app.services.automations.wake import _resolve_runtime

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            app_id, av_id = await _seed_app_and_version(db, creator_user_id=user_id)
            deployment_id = await _seed_runtime_deployment(
                db, app_id=app_id, app_version_id=av_id
            )
            await _seed_app_install(
                db,
                installer_user_id=user_id,
                app_id=app_id,
                app_version_id=av_id,
                runtime_deployment_id=deployment_id,
            )
            app_action_id = await _seed_app_action(db, app_version_id=av_id)
            run_id = await _seed_run_with_app_invoke(
                db, owner_user_id=user_id, app_action_id=app_action_id
            )
            await db.commit()

        async with session_maker() as db:
            run = await db.get(AutomationRun, run_id)
            assert run is not None
            return await _resolve_runtime(db, run)

    deployment = asyncio.run(go())
    assert deployment is not None
    assert deployment.tenancy_model == "per_install"


@pytest.mark.unit
def test_resolve_runtime_returns_none_when_no_app_invoke_action(
    session_maker,
) -> None:
    """``agent.run``-only automations have no AppAction → None."""
    from app.models_automations import AutomationRun
    from app.services.automations.wake import _resolve_runtime

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            run_id = await _seed_run_with_app_invoke(
                db, owner_user_id=user_id, app_action_id=None
            )
            await db.commit()

        async with session_maker() as db:
            run = await db.get(AutomationRun, run_id)
            assert run is not None
            return await _resolve_runtime(db, run)

    deployment = asyncio.run(go())
    assert deployment is None


@pytest.mark.unit
def test_resolve_runtime_returns_none_when_install_has_no_deployment_id(
    session_maker,
) -> None:
    """Legacy install (no runtime_deployment_id) → None."""
    from app.models_automations import AutomationRun
    from app.services.automations.wake import _resolve_runtime

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            app_id, av_id = await _seed_app_and_version(db, creator_user_id=user_id)
            await _seed_app_install(
                db,
                installer_user_id=user_id,
                app_id=app_id,
                app_version_id=av_id,
                runtime_deployment_id=None,  # legacy install
            )
            app_action_id = await _seed_app_action(db, app_version_id=av_id)
            run_id = await _seed_run_with_app_invoke(
                db, owner_user_id=user_id, app_action_id=app_action_id
            )
            await db.commit()

        async with session_maker() as db:
            run = await db.get(AutomationRun, run_id)
            assert run is not None
            return await _resolve_runtime(db, run)

    deployment = asyncio.run(go())
    assert deployment is None


@pytest.mark.unit
def test_resolve_runtime_scopes_install_lookup_to_owner(session_maker) -> None:
    """An install owned by a DIFFERENT user must not satisfy the lookup.

    The resolver scopes via ``installer_user_id == automation.owner_user_id``
    so a stranger's install of the same app version doesn't accidentally
    drive the wake target.
    """
    from app.models_automations import AutomationRun
    from app.services.automations.wake import _resolve_runtime

    async def go():
        async with session_maker() as db:
            owner_id = await _seed_user(db)
            stranger_id = await _seed_user(db)
            app_id, av_id = await _seed_app_and_version(db, creator_user_id=owner_id)
            deployment_id = await _seed_runtime_deployment(
                db, app_id=app_id, app_version_id=av_id
            )
            # The install belongs to the stranger, not the automation owner.
            await _seed_app_install(
                db,
                installer_user_id=stranger_id,
                app_id=app_id,
                app_version_id=av_id,
                runtime_deployment_id=deployment_id,
            )
            app_action_id = await _seed_app_action(db, app_version_id=av_id)
            run_id = await _seed_run_with_app_invoke(
                db, owner_user_id=owner_id, app_action_id=app_action_id
            )
            await db.commit()

        async with session_maker() as db:
            run = await db.get(AutomationRun, run_id)
            assert run is not None
            return await _resolve_runtime(db, run)

    deployment = asyncio.run(go())
    assert deployment is None
