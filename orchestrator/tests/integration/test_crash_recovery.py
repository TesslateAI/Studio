"""Crash-recovery idempotency for automation dispatch (demo flow #15).

Two cases:

1. ``test_dispatch_idempotency_on_duplicate_event`` — a worker pod
   crashed mid-dispatch and the event was re-enqueued. The dispatcher
   must collapse to the existing run (same id, no duplicate execution).

2. ``test_dispatch_refuses_re_enqueue_for_terminal_run`` — the same
   event id arrives after the run already moved to a terminal status.
   The dispatcher must noop (NOT bump retry_count, NOT re-enqueue ARQ).

Both cases are exercised against a migrated SQLite (alembic head) so
the ``UNIQUE (automation_id, event_id)`` constraint is enforced exactly
as it would be in production.
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
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration / session fixtures
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
    db_path = tmp_path / "crash_recovery.db"
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
# Stub queue + redis
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
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"crash-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Crash Test User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation_with_action(
    db, *, owner_user_id: uuid.UUID
) -> uuid.UUID:
    from app.models_automations import AutomationAction, AutomationDefinition

    autom_id = uuid.uuid4()
    db.add(
        AutomationDefinition(
            id=autom_id,
            name="crash-test",
            owner_user_id=owner_user_id,
            workspace_scope="none",
            contract={
                "allowed_tools": [],
                "max_compute_tier": 0,
                "on_breach": "pause_for_approval",
            },
            max_compute_tier=0,
            is_active=True,
        )
    )
    db.add(
        AutomationAction(
            id=uuid.uuid4(),
            automation_id=autom_id,
            ordinal=0,
            action_type="gateway.send",
            config={"body": "noop"},
        )
    )
    await db.flush()
    return autom_id


async def _seed_event(db, *, automation_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import AutomationEvent

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        payload={"crash": "recovery"},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    return evt.id


async def _load_run(db, run_id: uuid.UUID):
    from app.models_automations import AutomationRun

    return (
        await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
    ).scalar_one()


async def _count_runs(db, *, automation_id: uuid.UUID, event_id: uuid.UUID) -> int:
    from app.models_automations import AutomationRun

    rows = (
        await db.execute(
            select(AutomationRun)
            .where(AutomationRun.automation_id == automation_id)
            .where(AutomationRun.event_id == event_id)
        )
    ).scalars().all()
    return len(rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_idempotency_on_duplicate_event(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """A duplicate dispatch (e.g. ARQ retry after crash) does NOT execute twice.

    Both calls must return the same run_id, the run row must be unique
    on (automation_id, event_id), and the gateway.send action must
    XADD only once.
    """
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async with session_maker() as db:
        owner_id = await _seed_user(db)
        automation_id = await _seed_automation_with_action(
            db, owner_user_id=owner_id
        )
        event_id = await _seed_event(db, automation_id=automation_id)
        await db.commit()

    # First dispatch — runs the action to completion.
    async with session_maker() as db:
        first = await dispatch_automation(
            db,
            automation_id=automation_id,
            event_id=event_id,
            worker_id="worker-A",
        )
    assert first.status == DispatchStatus.SUCCEEDED

    # Second dispatch with the SAME event_id — simulates ARQ retry after
    # a worker crash between commit and ack.
    async with session_maker() as db:
        second = await dispatch_automation(
            db,
            automation_id=automation_id,
            event_id=event_id,
            worker_id="worker-B",
        )

    assert first.run_id == second.run_id, (
        "duplicate dispatch must collapse to the same run_id "
        f"(got {first.run_id} vs {second.run_id})"
    )
    # The dispatcher distinguishes terminal-noop from inflight-noop; both
    # are acceptable for "did not re-execute".
    assert second.status in {
        DispatchStatus.NOOP_TERMINAL,
        DispatchStatus.NOOP_INFLIGHT,
        DispatchStatus.SUCCEEDED,
    }, second.status

    async with session_maker() as db:
        count = await _count_runs(
            db, automation_id=automation_id, event_id=event_id
        )
    assert count == 1, (
        f"UNIQUE (automation_id, event_id) violated: {count} run rows for "
        "the same event"
    )

    # gateway.send executed exactly once -> exactly one XADD.
    assert len(stub_redis.xadds) == 1, (
        f"action re-executed on duplicate dispatch: {len(stub_redis.xadds)} XADDs"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_refuses_re_enqueue_for_terminal_run(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """A succeeded run rejects re-dispatch; retry_count stays at 0.

    Without ``force_retry=True`` the dispatcher's branch table returns
    NOOP_TERMINAL for any run already in {succeeded, failed, expired,
    cancelled}. The action must NOT re-fire and the queue must NOT see
    a fresh enqueue.
    """
    from app.services.automations import (
        DispatchStatus,
        dispatch_automation,
    )

    async with session_maker() as db:
        owner_id = await _seed_user(db)
        automation_id = await _seed_automation_with_action(
            db, owner_user_id=owner_id
        )
        event_id = await _seed_event(db, automation_id=automation_id)
        await db.commit()

    # Run to completion.
    async with session_maker() as db:
        first = await dispatch_automation(
            db, automation_id=automation_id, event_id=event_id
        )
    assert first.status == DispatchStatus.SUCCEEDED

    # Snapshot the row so we can compare retry_count + spend after.
    async with session_maker() as db:
        before = await _load_run(db, first.run_id)
    assert before.status == "succeeded"
    initial_retry = before.retry_count
    initial_xadds = len(stub_redis.xadds)
    initial_queue_calls = len(stub_queue.calls)

    # Re-dispatch the same event id — should noop.
    async with session_maker() as db:
        second = await dispatch_automation(
            db, automation_id=automation_id, event_id=event_id
        )
    assert second.status == DispatchStatus.NOOP_TERMINAL, second.status
    assert second.run_id == first.run_id

    # retry_count NOT bumped (only paused/expired/cancelled paths bump it).
    async with session_maker() as db:
        after = await _load_run(db, first.run_id)
    assert after.retry_count == initial_retry, (
        f"retry_count bumped on terminal re-dispatch: {initial_retry} -> "
        f"{after.retry_count}"
    )
    assert after.status == "succeeded"

    # No fresh side effects.
    assert len(stub_redis.xadds) == initial_xadds, (
        "action re-executed on terminal re-dispatch (XADD count grew)"
    )
    assert len(stub_queue.calls) == initial_queue_calls, (
        "re-enqueue happened on terminal re-dispatch (task queue called)"
    )
