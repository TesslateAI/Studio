"""Phase 1 — unit tests for ``app.routers.automations``.

Hermetic FastAPI ``TestClient`` tests against a SQLite database upgraded to
alembic ``head`` (mirrors the dispatcher tests' SQLite-fixture pattern).
We override two dependencies on the FastAPI app:

* ``get_db``                       → session bound to the migrated SQLite engine.
* ``current_active_user``          → returns a seeded :class:`User`.
* ``services.task_queue.get_task_queue`` → in-process stub queue so the
  manual-run endpoint never reaches Redis.

Out of scope for these tests:

* The dispatcher's actual execution path (covered in
  ``tests/services/automations/test_dispatcher.py``).
* External-API-key auth flow (the same dependency surface; integration
  tests cover the API-key wrapper).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Shared SQLite migration fixtures
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001 - SA event signature
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
    db_path = tmp_path / "automations_router.db"
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
            email=f"router-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Router User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


# ---------------------------------------------------------------------------
# FastAPI test client + dep overrides
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_queue(monkeypatch: pytest.MonkeyPatch):
    """Replace the task-queue backend with an in-process stub."""

    class _StubQueue:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        async def enqueue(self, name: str, *args: Any, **kwargs: Any) -> str:
            self.calls.append((name, args, kwargs))
            return f"job-{len(self.calls)}"

    queue = _StubQueue()
    monkeypatch.setattr(
        "app.services.task_queue.get_task_queue", lambda: queue, raising=True
    )
    return queue


@pytest.fixture
def stub_dispatcher(monkeypatch: pytest.MonkeyPatch, session_maker):
    """Stub :func:`dispatch_automation` for router tests.

    The router calls the dispatcher synchronously so the response carries a
    real ``run_id`` (see :func:`run_automation`). Phase B preflight would
    reach for Redis (LiteLLM key minting, gateway delivery stream, etc.),
    which the SQLite-only router tests don't host. The stub does only what
    the router contract needs: insert the run row via the same
    ``_upsert_run`` the dispatcher uses, then return a ``DispatchResult``
    so the response body is well-formed.

    Tests that want to inspect dispatch internals belong in
    ``tests/services/automations/test_dispatcher.py``.
    """
    calls: list[tuple[str, str, str]] = []

    async def _stub_dispatch(
        db,
        *,
        automation_id,
        event_id,
        worker_id,
        force_retry: bool = False,
    ):
        from app.services.automations.dispatcher import (
            DispatchResult,
            DispatchStatus,
            _upsert_run,
        )

        calls.append((str(automation_id), str(event_id), worker_id))
        run, _inserted = await _upsert_run(
            db,
            automation_id=automation_id,
            event_id=event_id,
            worker_id=worker_id,
        )
        await db.commit()
        return DispatchResult(
            status=DispatchStatus.SUCCEEDED,
            run_id=run.id,
            run_status=run.status,
            reason="stubbed in router tests",
        )

    monkeypatch.setattr(
        "app.services.automations.dispatcher.dispatch_automation",
        _stub_dispatch,
        raising=True,
    )
    _stub_dispatch.calls = calls  # type: ignore[attr-defined]
    return _stub_dispatch


@pytest.fixture
def app_client(session_maker, stub_queue, stub_dispatcher):
    """Return ``(client, owner_user_id, session_maker)``.

    Builds a fresh FastAPI app instance with only the automations router
    mounted so we don't need to boot the rest of the orchestrator's
    middleware stack.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.models_auth import User
    from app.routers import automations as automations_router
    from app.users import current_active_user

    # Seed an owner user up front so the override dep can return them.
    async def _seed():
        async with session_maker() as db:
            uid = await _seed_user(db)
            await db.commit()
            return uid

    owner_id = asyncio.run(_seed())

    app = FastAPI()
    app.include_router(automations_router.router)

    async def _override_db():
        async with session_maker() as db:
            yield db

    async def _override_user():
        # Build a transient User pointed at the seeded id; downstream
        # routes only read .id / .is_superuser, never re-fetch from DB.
        u = User(
            id=owner_id,
            email="router@example.com",
            hashed_password="",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Router User",
        )
        return u

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = _override_user

    client = TestClient(app)
    yield client, owner_id, session_maker


# ---------------------------------------------------------------------------
# Helper payloads
# ---------------------------------------------------------------------------


def _good_create_payload() -> dict[str, Any]:
    return {
        "name": "router-test-automation",
        "workspace_scope": "none",
        "contract": {
            "allowed_tools": ["read_file"],
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
        "max_compute_tier": 0,
        "triggers": [{"kind": "manual", "config": {}}],
        "actions": [
            {
                "action_type": "gateway.send",
                "config": {"body_template": "hello {x}"},
                "ordinal": 0,
            }
        ],
        "delivery_targets": [],
    }


# ---------------------------------------------------------------------------
# Tests — CRUD
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_rejects_missing_contract(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload.pop("contract")
    resp = client.post("/api/automations", json=payload)
    # Pydantic surfaces the missing required field as 422; that's fine —
    # the contract guard is enforced at the validation layer.
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_rejects_empty_contract(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["contract"] = {}
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_rejects_zero_actions(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["actions"] = []
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_rejects_multi_actions(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["actions"] = [
        {"action_type": "gateway.send", "config": {}, "ordinal": 0},
        {"action_type": "gateway.send", "config": {}, "ordinal": 1},
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_persists_definition_with_children(app_client) -> None:
    client, owner_id, _ = app_client
    resp = client.post("/api/automations", json=_good_create_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "router-test-automation"
    assert body["owner_user_id"] == str(owner_id)
    assert body["is_active"] is True
    assert len(body["triggers"]) == 1
    assert body["triggers"][0]["kind"] == "manual"
    assert len(body["actions"]) == 1
    assert body["actions"][0]["action_type"] == "gateway.send"
    assert body["delivery_targets"] == []


@pytest.mark.unit
def test_get_returns_404_for_unknown_id(app_client) -> None:
    client, _, _ = app_client
    resp = client.get(f"/api/automations/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.unit
def test_list_returns_owned_automations(app_client) -> None:
    client, _, _ = app_client
    client.post("/api/automations", json=_good_create_payload())
    client.post("/api/automations", json={**_good_create_payload(), "name": "second"})
    resp = client.get("/api/automations")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    names = sorted(i["name"] for i in items)
    assert names == ["router-test-automation", "second"]


@pytest.mark.unit
def test_patch_updates_name_and_contract(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    resp = client.patch(
        f"/api/automations/{aid}",
        json={
            "name": "renamed",
            "contract": {
                "allowed_tools": [],
                "max_compute_tier": 1,
                "on_breach": "hard_stop",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["contract"]["max_compute_tier"] == 1
    assert body["contract"]["on_breach"] == "hard_stop"


@pytest.mark.unit
def test_patch_replace_triggers(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    resp = client.patch(
        f"/api/automations/{aid}",
        json={
            "triggers": [
                {"kind": "cron", "config": {"expr": "0 * * * *"}},
                {"kind": "manual", "config": {}},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert sorted(t["kind"] for t in body["triggers"]) == ["cron", "manual"]


@pytest.mark.unit
def test_delete_soft_default(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    resp = client.delete(f"/api/automations/{aid}")
    assert resp.status_code == 200
    assert resp.json()["hard"] is False
    # Definition still readable but is_active=False.
    fetched = client.get(f"/api/automations/{aid}").json()
    assert fetched["is_active"] is False
    assert fetched["paused_reason"] == "deleted_by_user"


@pytest.mark.unit
def test_delete_hard_when_no_runs(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    resp = client.delete(f"/api/automations/{aid}?hard=true")
    assert resp.status_code == 200
    assert resp.json()["hard"] is True
    assert client.get(f"/api/automations/{aid}").status_code == 404


# ---------------------------------------------------------------------------
# Tests — manual run + enqueue
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_manual_run_creates_event_and_run(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    resp = client.post(f"/api/automations/{aid}/run", json={"payload": {"x": 1}})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["automation_id"] == aid
    assert body["status"] == "queued"
    assert uuid.UUID(body["run_id"])
    assert uuid.UUID(body["event_id"])


@pytest.mark.unit
def test_manual_run_invokes_dispatcher(app_client, stub_dispatcher) -> None:
    """Manual run dispatches synchronously rather than enqueueing.

    The router used to ``enqueue("dispatch_automation_task", ...)``, but a
    pre-created run at ``status='queued'`` collided with the dispatcher's
    idempotency noop branch and the run deadlocked. The new contract is:
    the router calls :func:`dispatch_automation` inline so the dispatcher's
    ``_upsert_run`` is the sole creator of the run row.
    """
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    resp = client.post(f"/api/automations/{aid}/run", json={})
    assert resp.status_code == 202

    body = resp.json()
    assert any(
        call[0] == aid and call[1] == body["event_id"]
        for call in stub_dispatcher.calls  # type: ignore[attr-defined]
    ), (
        f"expected dispatcher call for automation={aid} "
        f"event={body['event_id']}; got {stub_dispatcher.calls!r}"  # type: ignore[attr-defined]
    )


@pytest.mark.unit
def test_manual_run_rejects_inactive(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    client.delete(f"/api/automations/{aid}")  # soft-delete → is_active=False
    resp = client.post(f"/api/automations/{aid}/run", json={})
    assert resp.status_code == 409


@pytest.mark.unit
def test_list_runs_returns_manual_run(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    run = client.post(f"/api/automations/{aid}/run", json={}).json()
    runs = client.get(f"/api/automations/{aid}/runs").json()
    assert any(r["id"] == run["run_id"] for r in runs)


@pytest.mark.unit
def test_get_run_returns_detail(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    run = client.post(f"/api/automations/{aid}/run", json={}).json()
    detail = client.get(f"/api/automations/{aid}/runs/{run['run_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["id"] == run["run_id"]
    assert body["status"] == "queued"
    assert body["artifacts"] == []
    assert body["approval_requests"] == []


@pytest.mark.unit
def test_artifact_404_when_missing(app_client) -> None:
    client, _, _ = app_client
    created = client.post("/api/automations", json=_good_create_payload()).json()
    aid = created["id"]
    run = client.post(f"/api/automations/{aid}/run", json={}).json()
    resp = client.get(
        f"/api/automations/{aid}/runs/{run['run_id']}/artifacts/{uuid.uuid4()}"
    )
    assert resp.status_code == 404
