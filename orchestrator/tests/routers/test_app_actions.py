"""Phase 1 — unit tests for ``app.routers.app_actions``.

Hermetic FastAPI ``TestClient`` tests that cover:

* GET listing of actions for an installed app.
* POST invocation — happy path (dispatcher monkeypatched), schema-error,
  not-found, and access-control branches.

We monkeypatch ``app.routers.app_actions.dispatch_app_action`` so the
router's behavior is exercised in isolation from the real dispatcher
plumbing (httpx, k8s, billing). The dispatcher itself is covered by
``tests/services/apps/test_action_dispatcher.py``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# SQLite migrate fixture (mirrors test_automations.py)
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "app_actions_router.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
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
            email=f"actions-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Action User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_marketplace_app(db, *, owner_id: uuid.UUID) -> uuid.UUID:
    from app.models import MarketplaceApp

    app_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:6]
    db.add(
        MarketplaceApp(
            id=app_id,
            slug=f"app-{suffix}",
            name=f"App {suffix}",
            handle=f"act-{suffix}",
            creator_user_id=owner_id,
            category="utility",
            state="approved",
        )
    )
    await db.flush()
    return app_id


async def _seed_app_version(db, *, app_id: uuid.UUID) -> uuid.UUID:
    from app.models import AppVersion

    version_id = uuid.uuid4()
    db.add(
        AppVersion(
            id=version_id,
            app_id=app_id,
            version="0.1.0",
            manifest_schema_version="v8",
            manifest_hash="hash-test",
            feature_set_hash="features-test",
            manifest_json={
                "manifest_schema_version": "v8",
                "app": {"slug": "x"},
                "runtime": {"tenancy_model": "per_install"},
                "billing": {},
            },
            approval_state="stage2_approved",
        )
    )
    await db.flush()
    return version_id


async def _seed_app_action(
    db, *, app_version_id: uuid.UUID, name: str = "ping"
) -> uuid.UUID:
    from app.models_automations import AppAction

    action_id = uuid.uuid4()
    db.add(
        AppAction(
            id=action_id,
            app_version_id=app_version_id,
            name=name,
            handler={"kind": "http_post", "path": "/ping"},
            input_schema={"type": "object", "properties": {"who": {"type": "string"}}},
            output_schema={"type": "object"},
        )
    )
    await db.flush()
    return action_id


async def _seed_app_instance(
    db,
    *,
    installer_user_id: uuid.UUID,
    app_id: uuid.UUID,
    app_version_id: uuid.UUID,
) -> uuid.UUID:
    from app.models_automations import AppInstance

    instance_id = uuid.uuid4()
    db.add(
        AppInstance(
            id=instance_id,
            app_id=app_id,
            app_version_id=app_version_id,
            installer_user_id=installer_user_id,
            state="installed",
        )
    )
    await db.flush()
    return instance_id


# ---------------------------------------------------------------------------
# Test client + dependency overrides
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(session_maker, monkeypatch):
    """Return ``(client, owner_id, instance_id, action_id)``."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.models_auth import User
    from app.routers import app_actions as app_actions_router
    from app.users import current_active_user

    async def _seed_all():
        async with session_maker() as db:
            uid = await _seed_user(db)
            marketplace_id = await _seed_marketplace_app(db, owner_id=uid)
            version_id = await _seed_app_version(db, app_id=marketplace_id)
            action_id = await _seed_app_action(db, app_version_id=version_id)
            inst_id = await _seed_app_instance(
                db,
                installer_user_id=uid,
                app_id=marketplace_id,
                app_version_id=version_id,
            )
            await db.commit()
            return uid, inst_id, action_id

    owner_id, instance_id, action_id = asyncio.run(_seed_all())

    app = FastAPI()
    app.include_router(app_actions_router.router)

    async def _override_db():
        async with session_maker() as db:
            yield db

    async def _override_user():
        return User(
            id=owner_id,
            email="actions@example.com",
            hashed_password="",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Action User",
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = _override_user

    client = TestClient(app)
    yield client, owner_id, instance_id, action_id


# ---------------------------------------------------------------------------
# GET /api/apps/{instance}/actions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_actions_returns_seeded_action(app_client) -> None:
    client, _, instance_id, action_id = app_client
    resp = client.get(f"/api/apps/{instance_id}/actions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["app_instance_id"] == str(instance_id)
    names = [a["name"] for a in body["actions"]]
    assert names == ["ping"]
    assert body["actions"][0]["id"] == str(action_id)
    assert body["actions"][0]["input_schema"] is not None


@pytest.mark.unit
def test_list_actions_404_for_missing_instance(app_client) -> None:
    client, _, _, _ = app_client
    resp = client.get(f"/api/apps/{uuid.uuid4()}/actions")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/apps/{instance}/actions/{name}
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_invoke_returns_dispatcher_result(app_client, monkeypatch) -> None:
    client, _, instance_id, _ = app_client

    from app.routers import app_actions as app_actions_router
    from app.services.apps.action_dispatcher import ActionDispatchResult

    async def _stub(db, **kwargs):  # noqa: ARG001
        return ActionDispatchResult(
            output={"pong": True},
            artifacts=[],
            spend_usd=Decimal("0.0001"),
            duration_seconds=0.123,
            error=None,
        )

    monkeypatch.setattr(app_actions_router, "dispatch_app_action", _stub)

    resp = client.post(
        f"/api/apps/{instance_id}/actions/ping", json={"input": {"who": "world"}}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output"] == {"pong": True}
    assert body["artifacts"] == []
    assert body["error"] is None
    assert float(body["duration_seconds"]) == pytest.approx(0.123)


@pytest.mark.unit
def test_invoke_input_invalid_returns_400(app_client, monkeypatch) -> None:
    client, _, instance_id, _ = app_client

    from app.routers import app_actions as app_actions_router
    from app.services.apps.action_dispatcher import ActionInputInvalid

    async def _stub(db, **kwargs):  # noqa: ARG001
        raise ActionInputInvalid("missing required: who")

    monkeypatch.setattr(app_actions_router, "dispatch_app_action", _stub)

    resp = client.post(f"/api/apps/{instance_id}/actions/ping", json={"input": {}})
    assert resp.status_code == 400, resp.text
    assert "missing required" in resp.json()["detail"]


@pytest.mark.unit
def test_invoke_action_not_found_returns_404(app_client, monkeypatch) -> None:
    client, _, instance_id, _ = app_client

    from app.routers import app_actions as app_actions_router
    from app.services.apps.action_dispatcher import AppActionNotFound

    async def _stub(db, **kwargs):  # noqa: ARG001
        raise AppActionNotFound("action 'unknown' not declared")

    monkeypatch.setattr(app_actions_router, "dispatch_app_action", _stub)

    resp = client.post(f"/api/apps/{instance_id}/actions/unknown", json={"input": {}})
    assert resp.status_code == 404


@pytest.mark.unit
def test_invoke_dispatch_failed_returns_502(app_client, monkeypatch) -> None:
    client, _, instance_id, _ = app_client

    from app.routers import app_actions as app_actions_router
    from app.services.apps.action_dispatcher import ActionDispatchFailed

    async def _stub(db, **kwargs):  # noqa: ARG001
        raise ActionDispatchFailed("upstream 500", status=500, body="oops")

    monkeypatch.setattr(app_actions_router, "dispatch_app_action", _stub)

    resp = client.post(f"/api/apps/{instance_id}/actions/ping", json={"input": {}})
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["upstream_status"] == 500
    assert detail["upstream_body"] == "oops"


@pytest.mark.unit
def test_invoke_handler_not_supported_returns_501(app_client, monkeypatch) -> None:
    client, _, instance_id, _ = app_client

    from app.routers import app_actions as app_actions_router
    from app.services.apps.action_dispatcher import ActionHandlerNotSupported

    async def _stub(db, **kwargs):  # noqa: ARG001
        raise ActionHandlerNotSupported("k8s_job needs DEPLOYMENT_MODE=kubernetes")

    monkeypatch.setattr(app_actions_router, "dispatch_app_action", _stub)

    resp = client.post(f"/api/apps/{instance_id}/actions/ping", json={"input": {}})
    assert resp.status_code == 501


@pytest.mark.unit
def test_invoke_404_for_missing_instance(app_client) -> None:
    client, _, _, _ = app_client
    resp = client.post(
        f"/api/apps/{uuid.uuid4()}/actions/ping", json={"input": {}}
    )
    assert resp.status_code == 404
