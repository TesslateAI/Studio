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
from sqlalchemy import event
from sqlalchemy import insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Shared SQLite migration fixtures
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001 - SA event signature
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


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


# Stable UUID for the seeded system agent used by ``_good_create_payload``.
# System agents bypass the library-scope check in
# ``services/marketplace_agent_scope.resolve_agent_in_user_scope``, so the
# test can reuse one fixture-seeded row across every CRUD case without
# also needing a ``UserPurchasedAgent`` link per test user.
_TEST_SYSTEM_AGENT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a9e7")


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


async def _seed_system_agent(db) -> uuid.UUID:
    """Insert a system MarketplaceAgent with the well-known test UUID.

    Anchored to the ``tesslate-official`` system source seeded by alembic
    ``0088_marketplace_sources`` so the NOT NULL constraint on
    ``marketplace_agents.source_id`` is satisfied. Idempotent — a duplicate
    insert across the same test DB returns the existing row's id.
    """
    from app.models import MarketplaceAgent

    existing = await db.get(MarketplaceAgent, _TEST_SYSTEM_AGENT_ID)
    if existing is not None:
        return existing.id

    # Mirrors the constant in alembic/versions/0088_marketplace_sources.py.
    tesslate_official_source_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    await db.execute(
        core_insert(MarketplaceAgent.__table__).values(
            id=_TEST_SYSTEM_AGENT_ID,
            name="Router-Test System Agent",
            slug="router-test-system-agent",
            description="System agent seeded for routers/test_automations.py",
            category="builder",
            item_type="agent",
            agent_type="IterativeAgent",
            pricing_type="free",
            source_id=tesslate_official_source_id,
            is_active=True,
            is_system=True,
            is_published=True,
        )
    )
    await db.flush()
    return _TEST_SYSTEM_AGENT_ID


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
    monkeypatch.setattr("app.services.task_queue.get_task_queue", lambda: queue, raising=True)
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

    # Seed an owner user + the well-known system agent up front so the
    # override dep can return the user and ``_good_create_payload`` has a
    # valid ``agent_id`` for ``agent.run`` actions.
    async def _seed():
        async with session_maker() as db:
            uid = await _seed_user(db)
            await _seed_system_agent(db)
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
    # Uses ``agent.run`` so the fixture stays minimal — gateway.send now
    # requires a delivery_target, and a real CommunicationDestination row
    # would force every test to seed one. gateway.send-specific validation
    # has its own dedicated tests below.
    #
    # ``config.agent_id`` references the seeded system agent (see
    # ``_seed_system_agent``). System agents bypass the per-user library
    # check, so the same UUID works for every test owner without extra
    # ``UserPurchasedAgent`` plumbing.
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
                "action_type": "agent.run",
                "config": {"agent_id": str(_TEST_SYSTEM_AGENT_ID), "prompt": "noop"},
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
def test_create_accepts_multi_actions(app_client) -> None:
    """Multi-step automations are accepted as of issue #469 / Phase A —
    the workflow engine walks ordinals when len(actions) > 1. This
    test used to assert 422; relaxing it to 201 codifies the new
    contract."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["actions"] = [
        {
            "action_type": "agent.run",
            "config": {"agent_id": str(_TEST_SYSTEM_AGENT_ID), "prompt": "a"},
            "ordinal": 0,
        },
        {
            "action_type": "agent.run",
            "config": {"agent_id": str(_TEST_SYSTEM_AGENT_ID), "prompt": "b"},
            "ordinal": 1,
        },
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["actions"]) == 2


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
    assert body["actions"][0]["action_type"] == "agent.run"
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
                {
                    "kind": "cron",
                    "config": {"expression": "0 * * * *", "timezone": "UTC"},
                },
                {"kind": "manual", "config": {}},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert sorted(t["kind"] for t in body["triggers"]) == ["cron", "manual"]


# ---------------------------------------------------------------------------
# Schedule trigger + gateway.send delivery validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_rejects_invalid_cron_expression(app_client) -> None:
    """4-field cron used to be silently coerced to empty string."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [{"kind": "cron", "config": {"expression": "* * * *"}}]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "expression" in resp.text.lower()


@pytest.mark.unit
def test_create_rejects_empty_cron_expression(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [{"kind": "cron", "config": {"expression": ""}}]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_rejects_cron_without_timezone(app_client) -> None:
    """Empty / missing timezone used to silently default to UTC."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [{"kind": "cron", "config": {"expression": "*/5 * * * *"}}]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "timezone" in resp.text.lower()


@pytest.mark.unit
def test_create_rejects_cron_with_empty_timezone(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [
        {
            "kind": "cron",
            "config": {"expression": "*/5 * * * *", "timezone": ""},
        }
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "timezone" in resp.text.lower()


@pytest.mark.unit
def test_create_rejects_cron_with_invalid_timezone(app_client) -> None:
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [
        {
            "kind": "cron",
            "config": {
                "expression": "*/5 * * * *",
                "timezone": "Mars/Olympus_Mons",
            },
        }
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "timezone" in resp.text.lower()


@pytest.mark.unit
def test_create_populates_next_run_at_for_cron(app_client) -> None:
    """Previously NULL → cron producer fired on the next leader-tick."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [
        {
            "kind": "cron",
            "config": {"expression": "*/5 * * * *", "timezone": "UTC"},
        }
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 201, resp.text
    trig = resp.json()["triggers"][0]
    assert trig["next_run_at"] is not None
    # Should be in the future, not "now or earlier". SQLite drops tz info
    # in the JSON serialization, so coerce to UTC-aware before comparing.
    nxt = datetime.fromisoformat(trig["next_run_at"].replace("Z", "+00:00"))
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=UTC)
    assert nxt > datetime.now(UTC)


@pytest.mark.unit
def test_create_rejects_six_field_cron_expression(app_client) -> None:
    """6-field (seconds-first) cron used to be accepted by croniter and
    silently quantized by the producer to multi-minute boundaries —
    the user's '*/30 * * * * *' (every 30s) would actually fire at
    coarser intervals with no warning."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [
        {
            "kind": "cron",
            "config": {
                "expression": "*/30 * * * * *",
                "timezone": "UTC",
            },
        }
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "5-field" in resp.text or "sub-minute" in resp.text


@pytest.mark.unit
def test_create_rejects_seven_field_cron_expression(app_client) -> None:
    """7-field (seconds + year) cron has the same coercion problem."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["triggers"] = [
        {
            "kind": "cron",
            "config": {
                "expression": "0 */30 * * * * 2026",
                "timezone": "UTC",
            },
        }
    ]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_rejects_gateway_send_without_delivery_target(app_client) -> None:
    """gateway.send + zero delivery_targets used to save as 'Active'."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["actions"] = [
        {
            "action_type": "gateway.send",
            "config": {"body": "hello"},
            "ordinal": 0,
        }
    ]
    payload["delivery_targets"] = []
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "delivery target" in resp.text.lower()


@pytest.mark.unit
def test_create_rejects_gateway_send_with_empty_body(app_client) -> None:
    """gateway.send used to accept config={}."""
    client, _, _ = app_client
    payload = _good_create_payload()
    payload["actions"] = [{"action_type": "gateway.send", "config": {}, "ordinal": 0}]
    resp = client.post("/api/automations", json=payload)
    assert resp.status_code == 422, resp.text
    assert "body" in resp.text.lower()


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
    resp = client.get(f"/api/automations/{aid}/runs/{run['run_id']}/artifacts/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — app-instance scoping (drawer filter + runs-by-install)
# ---------------------------------------------------------------------------


async def _seed_app_install(db, owner_id: uuid.UUID) -> uuid.UUID:
    """Insert a minimal MarketplaceApp + AppVersion + AppInstance owned by
    ``owner_id`` and return the install id.

    Bypasses the full install saga — we only need a valid FK target for
    ``automation_definitions.app_instance_id`` and a row whose
    ``installer_user_id`` matches the test user.
    """
    from app.models import AppVersion, MarketplaceApp
    from app.models_automations import AppInstance

    # 0088_marketplace_sources made marketplace_apps/app_versions.source_id
    # NOT NULL. The "local" sentinel source is seeded by 0088 with this UUID.
    LOCAL_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

    app_id = uuid.uuid4()
    db.add(
        MarketplaceApp(
            id=app_id,
            slug=f"app-{app_id.hex[:8]}",
            name="Test App",
            category="utility",
            creator_user_id=owner_id,
            state="approved",
            source_id=LOCAL_SOURCE_ID,
        )
    )
    version_id = uuid.uuid4()
    db.add(
        AppVersion(
            id=version_id,
            app_id=app_id,
            version="1.0.0",
            manifest_schema_version="2026-05",
            manifest_json={"manifest_schema_version": "2026-05"},
            manifest_hash="x" * 64,
            feature_set_hash="y" * 64,
            approval_state="stage1_approved",
            source_id=LOCAL_SOURCE_ID,
        )
    )
    install_id = uuid.uuid4()
    db.add(
        AppInstance(
            id=install_id,
            app_id=app_id,
            app_version_id=version_id,
            installer_user_id=owner_id,
            state="installed",
        )
    )
    await db.flush()
    return install_id


@pytest.mark.unit
def test_list_filters_by_app_instance_id(app_client) -> None:
    client, owner_id, session_maker = app_client

    async def _seed():
        async with session_maker() as db:
            iid = await _seed_app_install(db, owner_id)
            await db.commit()
            return iid

    install_id = asyncio.run(_seed())

    # One scoped to the install, one unscoped.
    scoped = client.post(
        "/api/automations",
        json={
            **_good_create_payload(),
            "name": "scoped",
            "app_instance_id": str(install_id),
        },
    )
    assert scoped.status_code == 201, scoped.text
    unscoped = client.post(
        "/api/automations",
        json={**_good_create_payload(), "name": "unscoped"},
    )
    assert unscoped.status_code == 201, unscoped.text

    # Filtered list returns only the scoped row.
    resp = client.get(f"/api/automations?app_instance_id={install_id}")
    assert resp.status_code == 200, resp.text
    names = [i["name"] for i in resp.json()]
    assert names == ["scoped"]

    # Unfiltered list still returns both — preserves the global page's view.
    all_resp = client.get("/api/automations")
    all_names = sorted(i["name"] for i in all_resp.json())
    assert all_names == ["scoped", "unscoped"]


@pytest.mark.unit
def test_create_rejects_unknown_app_instance_id(app_client) -> None:
    client, _, _ = app_client
    resp = client.post(
        "/api/automations",
        json={
            **_good_create_payload(),
            "app_instance_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.unit
def test_runs_by_install_returns_runs_across_automations(app_client) -> None:
    client, owner_id, session_maker = app_client

    async def _seed():
        async with session_maker() as db:
            iid = await _seed_app_install(db, owner_id)
            await db.commit()
            return iid

    install_id = asyncio.run(_seed())

    # Two scoped automations; one unscoped (must NOT appear in the per-install runs).
    a1 = client.post(
        "/api/automations",
        json={
            **_good_create_payload(),
            "name": "a1",
            "app_instance_id": str(install_id),
        },
    ).json()
    a2 = client.post(
        "/api/automations",
        json={
            **_good_create_payload(),
            "name": "a2",
            "app_instance_id": str(install_id),
        },
    ).json()
    other = client.post("/api/automations", json={**_good_create_payload(), "name": "other"}).json()

    r1 = client.post(f"/api/automations/{a1['id']}/run", json={}).json()
    r2 = client.post(f"/api/automations/{a2['id']}/run", json={}).json()
    r_other = client.post(f"/api/automations/{other['id']}/run", json={}).json()

    resp = client.get(f"/api/automations/runs/by-install/{install_id}")
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert ids == {r1["run_id"], r2["run_id"]}
    assert r_other["run_id"] not in ids


@pytest.mark.unit
def test_runs_by_install_404_for_unknown_install(app_client) -> None:
    client, _, _ = app_client
    resp = client.get(f"/api/automations/runs/by-install/{uuid.uuid4()}")
    assert resp.status_code == 404
