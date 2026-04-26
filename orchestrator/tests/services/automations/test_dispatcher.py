"""Phase 1 — unit tests for ``services.automations.dispatcher``.

We exercise the dispatcher end-to-end against a SQLite database upgraded
to alembic ``head`` so the real ``automation_*`` tables (and their
``UNIQUE (automation_id, event_id)`` constraint) are in play. Tests
restrict themselves to direct calls into ``dispatch_automation`` and
assertions on the resulting ``AutomationRun`` rows.

Out of scope (handled in later phases):

* Real ``app.invoke`` execution (Wave 2B). Tests stub
  ``services.apps.action_dispatcher.dispatch`` via ``monkeypatch``.
* Real ``execute_agent_task`` execution. Tests assert the enqueue happened
  by stubbing the task-queue backend.
* Heartbeat sweep (Phase 4 controller). Phase 1 tests only confirm
  ``heartbeat_at`` is written.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# SQLite migration fixture (mirrors tests/migrations/test_0050_orchestration.py
# pattern -- alembic head against a temp file)
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    """SQLite has no ``now()``; register one so server_default=func.now() works."""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001 - SA event signature
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
    db_path = tmp_path / "dispatcher.db"
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
# Seed helpers — minimal rows so the dispatcher has something to chew on.
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    """Insert a bare User row that satisfies the FKs we touch.

    The User model requires ``name``/``username``/``slug``/``email``/
    ``hashed_password``; everything else has a default. We deliberately
    use raw INSERT via SQLAlchemy core to avoid pulling in the
    fastapi-users dependency just to construct an ORM object -- the
    only thing the dispatcher cares about is the ``users.id`` row
    existing as an FK target.
    """
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"test-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Test User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation(
    db,
    *,
    owner_user_id: uuid.UUID,
    contract: dict[str, Any] | None = None,
    is_active: bool = True,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="test-automation",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract=contract
        if contract is not None
        else {
            "allowed_tools": ["read_file"],
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
        max_compute_tier=0,
        is_active=is_active,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def _seed_event(
    db,
    *,
    automation_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationEvent

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        payload=payload or {"hello": "world"},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    return evt.id


async def _seed_action(
    db,
    *,
    automation_id: uuid.UUID,
    action_type: str,
    config: dict[str, Any] | None = None,
    app_action_id: uuid.UUID | None = None,
    ordinal: int = 0,
) -> uuid.UUID:
    from app.models_automations import AutomationAction

    act = AutomationAction(
        id=uuid.uuid4(),
        automation_id=automation_id,
        ordinal=ordinal,
        action_type=action_type,
        config=config or {},
        app_action_id=app_action_id,
    )
    db.add(act)
    await db.flush()
    return act.id


async def _seed_delivery_target(
    db,
    *,
    automation_id: uuid.UUID,
    destination_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationDeliveryTarget

    target = AutomationDeliveryTarget(
        id=uuid.uuid4(),
        automation_id=automation_id,
        destination_id=destination_id or uuid.uuid4(),
        ordinal=0,
        on_failure={"kind": "drop"},
    )
    db.add(target)
    await db.flush()
    return target.id


async def _load_run(db, run_id: uuid.UUID):
    from app.models_automations import AutomationRun

    return (
        await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
    ).scalar_one()


async def _count_artifacts(db, run_id: uuid.UUID) -> int:
    from app.models_automations import AutomationRunArtifact

    rows = (
        await db.execute(
            select(AutomationRunArtifact).where(
                AutomationRunArtifact.run_id == run_id
            )
        )
    ).scalars().all()
    return len(rows)


# ---------------------------------------------------------------------------
# Stub a TaskQueue + Redis for the dispatcher's enqueue/XADD paths.
# ---------------------------------------------------------------------------


class _StubQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue(self, name: str, *args: Any, **kwargs: Any) -> str:
        self.calls.append((name, args, kwargs))
        return f"job-{len(self.calls)}"


class _StubRedis:
    def __init__(self) -> None:
        self.xadds: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream: str, fields: dict[str, str], **_: Any) -> str:
        self.xadds.append((stream, dict(fields)))
        return "1-0"


@pytest.fixture
def stub_queue(monkeypatch: pytest.MonkeyPatch) -> _StubQueue:
    queue = _StubQueue()
    monkeypatch.setattr(
        "app.services.task_queue.get_task_queue", lambda: queue, raising=True
    )
    return queue


@pytest.fixture
def stub_redis(monkeypatch: pytest.MonkeyPatch) -> _StubRedis:
    redis = _StubRedis()

    async def _get():
        return redis

    monkeypatch.setattr(
        "app.services.cache_service.get_redis_client", _get, raising=True
    )
    return redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_idempotency_same_event_twice_returns_same_run(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """Two ``dispatch_automation`` calls collapse to one ``AutomationRun``."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                config={"body_template": "hello {hello}"},
            )
            await db.commit()

        async with session_maker() as db:
            r1 = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
                worker_id="worker-A",
            )

        async with session_maker() as db:
            r2 = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
                worker_id="worker-B",
            )

        return r1, r2

    r1, r2 = asyncio.run(go())
    assert r1.run_id == r2.run_id
    assert r1.status == DispatchStatus.SUCCEEDED
    # Second call sees the terminal row and noops without re-executing.
    assert r2.status == DispatchStatus.NOOP_TERMINAL
    # gateway.send only XADDed once.
    assert len(stub_redis.xadds) == 1


@pytest.mark.unit
def test_existing_paused_run_bumps_retry_count(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """Paused / cancelled runs are retryable -- second dispatch reruns."""
    from app.models_automations import AutomationRun
    from app.services.automations import dispatch_automation

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                config={"body": "hi"},
            )
            await db.commit()

        # First run -> succeeded.
        async with session_maker() as db:
            r1 = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

        # Hand-flip the row into 'paused' so the retry branch fires.
        async with session_maker() as db:
            run = await _load_run(db, r1.run_id)
            run.status = "paused"
            run.paused_reason = "manual hold"
            await db.commit()

        async with session_maker() as db:
            r2 = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

        async with session_maker() as db:
            after = await _load_run(db, r1.run_id)

        return r1, r2, after

    r1, r2, after = asyncio.run(go())
    assert r1.run_id == r2.run_id
    # The retry path bumped the counter and re-executed to terminal.
    assert after.retry_count == 1
    assert after.status == "succeeded"


@pytest.mark.unit
def test_contract_invalid_marks_failed_preflight(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """A contract missing required keys lands in failed_preflight."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            # Contract is missing 'max_compute_tier' -> ContractInvalid.
            automation_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                contract={"allowed_tools": ["read_file"]},
            )
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
            )
            await db.commit()

        async with session_maker() as db:
            result = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

        async with session_maker() as db:
            run = await _load_run(db, result.run_id)

        return result, run

    result, run = asyncio.run(go())
    assert result.status == DispatchStatus.FAILED
    assert run.status == "failed_preflight"
    assert "max_compute_tier" in (run.paused_reason or "")


@pytest.mark.unit
def test_inactive_automation_marks_failed_preflight(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                is_active=False,
            )
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
            )
            await db.commit()

        async with session_maker() as db:
            return await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

    result = asyncio.run(go())
    assert result.status == DispatchStatus.PAUSED
    assert result.run_status == "failed_preflight"
    assert "is_active" in (result.reason or "")


@pytest.mark.unit
def test_gateway_send_writes_envelope_and_delivery_receipt(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """gateway.send action XADDs a typed envelope and persists a receipt."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(
                db,
                automation_id=automation_id,
                payload={"name": "Tesslate"},
            )
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                config={
                    "body_template": "Hello {name}!",
                    "channel_config_id": str(uuid.uuid4()),
                    "session_key": "web:user:abc",
                },
            )
            await _seed_delivery_target(db, automation_id=automation_id)
            await db.commit()

        async with session_maker() as db:
            result = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

        async with session_maker() as db:
            run = await _load_run(db, result.run_id)
            artifacts = await _count_artifacts(db, result.run_id)

        return result, run, artifacts

    result, run, artifacts = asyncio.run(go())
    assert result.status == DispatchStatus.SUCCEEDED
    assert run.status == "succeeded"
    assert run.ended_at is not None
    assert run.heartbeat_at is not None
    assert run.worker_id is not None

    # XADD to the gateway delivery stream.
    assert len(stub_redis.xadds) == 1
    stream, fields = stub_redis.xadds[0]
    assert stream  # config-driven, but always non-empty
    assert fields["body"] == "Hello Tesslate!"
    assert fields["kind"] == "message"

    # One delivery receipt artifact for the configured target.
    assert artifacts == 1


@pytest.mark.unit
def test_agent_run_enqueues_execute_agent_task(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """agent.run actions enqueue ``execute_agent_task`` with the run_id."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="agent.run",
                config={"chat_id": str(uuid.uuid4()), "message": "go"},
            )
            await db.commit()

        async with session_maker() as db:
            return await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

    result = asyncio.run(go())
    assert result.status == DispatchStatus.SUCCEEDED
    assert len(stub_queue.calls) == 1
    name, args, _ = stub_queue.calls[0]
    assert name == "execute_agent_task"
    payload = args[0]
    assert payload["task_id"] == str(result.run_id)
    assert payload["automation_run_id"] == str(result.run_id)
    assert payload["automation_id"] == str(result.run_id) or payload[
        "automation_id"
    ]  # any non-empty UUID
    # Contract is forwarded so the agent loop can enforce it Phase 2.
    assert payload["contract"]["max_compute_tier"] == 0


@pytest.mark.unit
def test_app_invoke_calls_action_dispatcher_when_present(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """app.invoke routes to ``services.apps.action_dispatcher.dispatch``.

    The real module ships in Wave 2B; here we install an in-memory shim so
    the dispatcher's branch is exercised without the actual implementation.
    """
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    # Install a fake action_dispatcher module under services.apps.
    fake_module = type(sys)("app.services.apps.action_dispatcher")
    fake_module.dispatch = AsyncMock(
        return_value={"action_type": "app.invoke", "ok": True, "body": "done"}
    )
    monkeypatch.setitem(
        sys.modules, "app.services.apps.action_dispatcher", fake_module
    )

    # Also make the parent package expose it as an attribute so that
    # ``from ..apps import action_dispatcher`` resolves.
    import app.services.apps as apps_pkg

    monkeypatch.setattr(
        apps_pkg, "action_dispatcher", fake_module, raising=False
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            # app.invoke needs an app_action_id -- forge a random UUID since
            # the stub never inspects it.
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="app.invoke",
                config={"input": {"x": 1}},
                app_action_id=uuid.uuid4(),
            )
            await db.commit()

        async with session_maker() as db:
            return await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

    result = asyncio.run(go())
    assert result.status == DispatchStatus.SUCCEEDED
    fake_module.dispatch.assert_awaited_once()
    kwargs = fake_module.dispatch.await_args.kwargs
    assert kwargs["run_id"] == result.run_id
    assert kwargs["input"] == {"x": 1}


@pytest.mark.unit
def test_app_invoke_without_action_dispatcher_marks_failed(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Wave 2B isn't synthesised, app.invoke fails cleanly with reason."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    # Force the lazy import to fail so we exercise the NotImplementedError
    # branch without touching whatever happens to live in the package.
    import app.services.apps as apps_pkg

    if hasattr(apps_pkg, "action_dispatcher"):
        monkeypatch.delattr(apps_pkg, "action_dispatcher", raising=False)
    monkeypatch.setitem(sys.modules, "app.services.apps.action_dispatcher", None)

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="app.invoke",
                config={"input": {}},
                app_action_id=uuid.uuid4(),
            )
            await db.commit()

        async with session_maker() as db:
            result = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

        async with session_maker() as db:
            run = await _load_run(db, result.run_id)

        return result, run

    result, run = asyncio.run(go())
    assert result.status == DispatchStatus.FAILED
    assert run.status == "failed"
    assert "action_dispatcher" in (run.paused_reason or "")


@pytest.mark.unit
def test_more_than_one_action_is_rejected(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """Phase 1 only supports a single action per automation."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                ordinal=0,
            )
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                ordinal=1,
            )
            await db.commit()

        async with session_maker() as db:
            return await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

    result = asyncio.run(go())
    assert result.status == DispatchStatus.FAILED
    assert result.run_status == "failed_preflight"
    assert "single action" in (result.reason or "")


@pytest.mark.unit
def test_heartbeat_helper_bumps_timestamp(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """``update_run_heartbeat`` writes a fresh heartbeat_at and worker_id."""
    from app.services.automations import (
        dispatch_automation,
        update_run_heartbeat,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                config={"body": "x"},
            )
            await db.commit()

        async with session_maker() as db:
            result = await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

        async with session_maker() as db:
            before = await _load_run(db, result.run_id)
            hb_before = before.heartbeat_at
            # Sleep a tick to guarantee a strictly-later timestamp.
            await asyncio.sleep(0.01)
            await update_run_heartbeat(db, result.run_id, worker_id="worker-X")
            await db.commit()

        async with session_maker() as db:
            after = await _load_run(db, result.run_id)

        return hb_before, after.heartbeat_at, after.worker_id

    hb_before, hb_after, worker_id = asyncio.run(go())
    assert hb_after >= hb_before
    assert worker_id == "worker-X"


@pytest.mark.unit
def test_dispatch_result_carries_terminal_status_for_succeeded(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """The DispatchResult's run_status reflects the persisted run row."""
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                config={"body": "x"},
            )
            await db.commit()

        async with session_maker() as db:
            return await dispatch_automation(
                db,
                automation_id=automation_id,
                event_id=event_id,
            )

    result = asyncio.run(go())
    assert result.status == DispatchStatus.SUCCEEDED
    assert result.run_status == "succeeded"
    assert result.run_id is not None
