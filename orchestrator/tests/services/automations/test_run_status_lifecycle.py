"""AutomationRun status lifecycle — async handoff vs synchronous actions.

Until 2026-04, dispatcher Phase D unconditionally wrote
``status="succeeded"`` after the action handler returned. That was wrong
for ``agent.run``: the handler only enqueues ``execute_agent_task`` and
returns ``{"enqueued": True}``, leaving the agent loop to run async in
the worker. The premature "succeeded" write meant a worker crash never
flipped the run to "failed", and ``heartbeat_sweep`` (which only watches
``status='running'``) had no recovery hook.

These tests pin the post-fix invariants:

* ``agent.run`` leaves ``run.status='running'`` + ``ended_at IS NULL``
  after dispatch returns. ``DispatchResult.run_status='running'`` mirrors
  the row so HTTP callers (manual run route) report the right state.
* ``gateway.send`` (synchronous action) still writes
  ``status='succeeded'`` + ``ended_at`` — guards against regressions in
  the non-async branch.
* ``_finalize_automation_run`` (worker writeback helper) only stamps a
  terminal status when the row is in ``{queued, preflight, running}``.
  Pre-existing ``cancelled`` / ``waiting_approval`` / ``succeeded`` rows
  are not stomped.
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
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# SQLite migration fixture — same shape as test_dispatcher.py.
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
    db_path = tmp_path / "lifecycle.db"
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
# Seed helpers — minimal copies from test_dispatcher.py to avoid coupling.
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"lc-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="LC User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation(db, *, owner_user_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="lifecycle-automation",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={
            "allowed_tools": ["read_file"],
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
        max_compute_tier=0,
        is_active=True,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def _seed_event(db, *, automation_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import AutomationEvent

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        payload={},
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
) -> None:
    from app.models_automations import AutomationAction

    db.add(
        AutomationAction(
            id=uuid.uuid4(),
            automation_id=automation_id,
            ordinal=0,
            action_type=action_type,
            config=config or {},
        )
    )
    await db.flush()


async def _load_run(db, run_id: uuid.UUID):
    from app.models_automations import AutomationRun

    return (
        await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
    ).scalar_one()


# ---------------------------------------------------------------------------
# Stubs — same as test_dispatcher.py.
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
# Phase D — async vs sync handoff
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_agent_run_dispatch_leaves_run_in_running_state(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """``agent.run`` is an async handoff — the worker writes the terminal
    status. Dispatcher must leave ``status='running'`` + ``ended_at IS
    NULL`` so heartbeat_sweep can recover dead workers."""
    from app.services.automations import DispatchStatus, dispatch_automation

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
            result = await dispatch_automation(
                db, automation_id=automation_id, event_id=event_id
            )

        async with session_maker() as db:
            run = await _load_run(db, result.run_id)
        return result, run

    result, run = asyncio.run(go())

    # The dispatcher's *own* outcome is still SUCCEEDED — it did its job
    # (enqueued the agent task). The run row's lifecycle is separate and
    # remains in flight until the worker writes the terminal state.
    assert result.status == DispatchStatus.SUCCEEDED
    assert result.run_status == "running"

    assert run.status == "running"
    assert run.ended_at is None
    assert run.heartbeat_at is not None  # refreshed in Phase D handoff branch
    # raw_output preserves the dispatcher receipt for traceability.
    assert isinstance(run.raw_output, dict)
    assert run.raw_output.get("enqueued") is True
    assert run.raw_output.get("action_type") == "agent.run"


@pytest.mark.unit
def test_gateway_send_dispatch_writes_succeeded_terminal(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """``gateway.send`` is synchronous — the dispatcher owns the terminal
    write. Regression guard: the sync branch must keep emitting
    ``succeeded`` + ``ended_at`` (this was the pre-fix behavior for *all*
    actions; only the async branch was wrong)."""
    from app.services.automations import DispatchStatus, dispatch_automation

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="gateway.send",
                config={
                    "body_template": "Hi {who}",
                    "channel_config_id": str(uuid.uuid4()),
                    "session_key": "web:user:1",
                },
            )
            await db.commit()

        async with session_maker() as db:
            result = await dispatch_automation(
                db, automation_id=automation_id, event_id=event_id
            )

        async with session_maker() as db:
            run = await _load_run(db, result.run_id)
        return result, run

    result, run = asyncio.run(go())
    assert result.status == DispatchStatus.SUCCEEDED
    assert result.run_status == "succeeded"
    assert run.status == "succeeded"
    assert run.ended_at is not None


# ---------------------------------------------------------------------------
# Worker writeback helper — _finalize_automation_run
# ---------------------------------------------------------------------------


async def _set_run_status(db, run_id: uuid.UUID, status: str) -> None:
    from app.models_automations import AutomationRun

    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run_id)
        .values(status=status)
    )
    await db.commit()


def _patch_session_local_for_worker_helpers(
    monkeypatch: pytest.MonkeyPatch, session_maker
) -> None:
    """Point ``app.database.AsyncSessionLocal`` at the test's session
    factory so worker helpers (which open their own session inside
    ``async with AsyncSessionLocal()``) see the test DB."""
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "AsyncSessionLocal", session_maker, raising=True)


@pytest.mark.unit
def test_finalize_writes_succeeded_when_run_is_running(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path — the worker calls _finalize after the agent loop;
    status flips ``running`` → ``succeeded`` + ``ended_at`` is set."""
    from app.services.automations import dispatch_automation
    from app.worker import _finalize_automation_run

    _patch_session_local_for_worker_helpers(monkeypatch, session_maker)

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
            result = await dispatch_automation(
                db, automation_id=automation_id, event_id=event_id
            )

        # Sanity: dispatcher left it at running.
        async with session_maker() as db:
            mid = await _load_run(db, result.run_id)
        assert mid.status == "running"
        assert mid.ended_at is None

        await _finalize_automation_run(
            result.run_id,
            status="succeeded",
            raw_output={"task_id": str(result.run_id), "iterations": 5},
        )

        async with session_maker() as db:
            return await _load_run(db, result.run_id)

    run = asyncio.run(go())
    assert run.status == "succeeded"
    assert run.ended_at is not None
    assert run.raw_output["iterations"] == 5


@pytest.mark.unit
@pytest.mark.parametrize(
    "preexisting_status",
    ["cancelled", "waiting_approval", "succeeded", "failed", "expired"],
)
def test_finalize_does_not_stomp_terminal_or_paused_rows(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    monkeypatch: pytest.MonkeyPatch,
    preexisting_status: str,
) -> None:
    """Race-safety: if a status outside {queued, preflight, running} is
    already on the row when the worker tries to finalize, the WHERE clause
    must reject the update. This protects user cancellations, ContractGate
    pauses, and prior terminal writes from being clobbered."""
    from app.services.automations import dispatch_automation
    from app.worker import _finalize_automation_run

    _patch_session_local_for_worker_helpers(monkeypatch, session_maker)

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
            result = await dispatch_automation(
                db, automation_id=automation_id, event_id=event_id
            )

        # Pre-set the row to the protected status before worker tries to
        # finalize. Models a user-cancellation or contract-breach pause
        # that landed first.
        async with session_maker() as db:
            await _set_run_status(db, result.run_id, preexisting_status)

        await _finalize_automation_run(
            result.run_id,
            status="succeeded",
            raw_output={"would": "overwrite"},
        )

        async with session_maker() as db:
            return await _load_run(db, result.run_id)

    run = asyncio.run(go())
    assert run.status == preexisting_status, (
        f"_finalize stomped {preexisting_status!r} — "
        f"WHERE-clause guard failed; got {run.status!r}"
    )


@pytest.mark.unit
def test_finalize_supports_failed_terminal(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exception path — worker passes ``status='failed'`` and the error
    in ``raw_output``; _finalize stamps both."""
    from app.services.automations import dispatch_automation
    from app.worker import _finalize_automation_run

    _patch_session_local_for_worker_helpers(monkeypatch, session_maker)

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
            result = await dispatch_automation(
                db, automation_id=automation_id, event_id=event_id
            )

        await _finalize_automation_run(
            result.run_id,
            status="failed",
            raw_output={"error": "ConnectionError: notion timeout", "error_type": "ConnectionError"},
        )

        async with session_maker() as db:
            return await _load_run(db, result.run_id)

    run = asyncio.run(go())
    assert run.status == "failed"
    assert run.ended_at is not None
    assert run.raw_output["error_type"] == "ConnectionError"


@pytest.mark.unit
def test_finalize_supports_waiting_approval_for_tool_pauses(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ApprovalRequired path — worker pauses the run as
    ``waiting_approval`` so heartbeat_sweep (which only reaps ``running``)
    leaves it alone until the operator unblocks it."""
    from app.services.automations import dispatch_automation
    from app.worker import _finalize_automation_run

    _patch_session_local_for_worker_helpers(monkeypatch, session_maker)

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
            result = await dispatch_automation(
                db, automation_id=automation_id, event_id=event_id
            )

        await _finalize_automation_run(
            result.run_id,
            status="waiting_approval",
            raw_output={
                "approval_required": {
                    "tool_name": "bash_exec",
                    "ticket_id": str(uuid.uuid4()),
                }
            },
        )

        async with session_maker() as db:
            return await _load_run(db, result.run_id)

    run = asyncio.run(go())
    assert run.status == "waiting_approval"
    assert run.ended_at is not None
    assert run.raw_output["approval_required"]["tool_name"] == "bash_exec"
