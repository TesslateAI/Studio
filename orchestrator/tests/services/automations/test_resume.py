"""Phase 2 Wave 2A — unit tests for ``services.automations.dispatcher.resume_run``.

The resume worker hydrates a serialized checkpoint and re-enters one of three
paths:

* ``redispatch`` — re-call the action dispatcher with the saved input.
* ``agent_continue`` — re-enqueue ``execute_agent_task`` with the saved
  message history.
* ``restart_from_checkpoint`` — re-enqueue with a clean history; the in-flight
  non-serializable tool was cancelled at pause time.

Tests stub the task queue and (for ``app.invoke``) the apps action dispatcher,
mirroring the pattern in ``test_dispatcher.py``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration + session fixtures
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
    db_path = tmp_path / "resume.db"
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
# Stubs (reuse the dispatcher-test pattern)
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


@pytest.fixture
def stub_app_action_dispatcher(monkeypatch: pytest.MonkeyPatch):
    """Provide a minimal ``services.apps.action_dispatcher`` so the resume
    redispatch path doesn't trip the Wave-2B NotImplementedError stub."""
    captured: list[dict[str, Any]] = []

    async def _dispatch(db, *, app_action_id, input, run_id):
        captured.append(
            {"app_action_id": app_action_id, "input": dict(input), "run_id": run_id}
        )
        return {"action_type": "app.invoke", "output": {"ok": True}, "input": dict(input)}

    fake = types.SimpleNamespace(dispatch=_dispatch)
    # Patch the import target — dispatcher does ``from ..apps import action_dispatcher``.
    # Two levels of cache to clobber:
    #   * ``sys.modules["app.services.apps.action_dispatcher"]`` for any code
    #     path that does ``import ...action_dispatcher`` directly.
    #   * The ``action_dispatcher`` attribute on the parent package — the
    #     ``from ..apps import action_dispatcher`` form returns the cached
    #     attribute when the real module has already been imported by an
    #     earlier test in the same session, ignoring sys.modules entirely.
    monkeypatch.setitem(
        sys.modules, "app.services.apps.action_dispatcher", fake
    )
    import app.services.apps as _apps_pkg

    monkeypatch.setattr(_apps_pkg, "action_dispatcher", fake, raising=False)
    return captured


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
            email=f"resume-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Resume Test",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_paused_run(
    db,
    *,
    owner_id: uuid.UUID,
    action_type: str,
    action_config: dict[str, Any],
    app_action_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models_automations import (
        AutomationAction,
        AutomationDefinition,
        AutomationRun,
    )

    automation_id = uuid.uuid4()
    db.add(
        AutomationDefinition(
            id=automation_id,
            name="resume-test",
            owner_user_id=owner_id,
            workspace_scope="none",
            contract={
                "allowed_tools": None,
                "max_compute_tier": 0,
            },
            max_compute_tier=0,
        )
    )
    db.add(
        AutomationAction(
            id=uuid.uuid4(),
            automation_id=automation_id,
            ordinal=0,
            action_type=action_type,
            config=action_config,
            app_action_id=app_action_id,
        )
    )
    run_id = uuid.uuid4()
    db.add(
        AutomationRun(
            id=run_id,
            automation_id=automation_id,
            event_id=None,
            status="waiting_approval",
            paused_reason="contract_violation: tool x",
            spend_usd=Decimal("0.01"),
        )
    )
    await db.flush()
    return automation_id, run_id


# ---------------------------------------------------------------------------
# Tests: redispatch path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resume_app_invoke_redispatches_with_saved_input(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
    stub_app_action_dispatcher,
) -> None:
    """``app.invoke`` resume re-calls the action dispatcher with the saved
    input from the checkpoint and finalizes the run as succeeded."""
    from app.models_automations import AutomationRun
    from app.services.automations import (
        DispatchStatus,
        resume_run,
        serialize_checkpoint,
        hydrate_checkpoint,
    )

    saved_input = {"customer_id": "cust-123", "amount": "5.00"}
    saved_app_action_id = uuid.uuid4()

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            automation_id, run_id = await _seed_paused_run(
                db,
                owner_id=owner,
                action_type="app.invoke",
                action_config={},
                app_action_id=saved_app_action_id,
            )
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            await serialize_checkpoint(
                db,
                run=run,
                action_type="app.invoke",
                action_state={
                    "input": saved_input,
                    "app_action_id": str(saved_app_action_id),
                    "partial_output": None,
                },
                pause_reason="budget_exceeded",
                contract_snapshot={
                    "allowed_tools": ["invoke_app_action"],
                    "max_compute_tier": 0,
                },
            )
            await db.commit()

        async with session_maker() as db:
            cp = await hydrate_checkpoint(db, run_id=run_id)
            assert cp is not None
            result = await resume_run(db, checkpoint=cp)
            await db.commit()

        async with session_maker() as db:
            final = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
        return result, final

    result, final = asyncio.run(go())

    assert result.status == DispatchStatus.SUCCEEDED
    assert final.status == "succeeded"
    # The fake action_dispatcher captured the saved input.
    assert len(stub_app_action_dispatcher) == 1
    assert stub_app_action_dispatcher[0]["input"] == saved_input
    assert stub_app_action_dispatcher[0]["app_action_id"] == saved_app_action_id


@pytest.mark.unit
def test_resume_gateway_send_re_emits_to_stream(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """``gateway.send`` resume re-renders the body and XADDs to the
    delivery stream."""
    from app.models_automations import AutomationRun
    from app.services.automations import (
        DispatchStatus,
        resume_run,
        serialize_checkpoint,
        hydrate_checkpoint,
    )

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            _, run_id = await _seed_paused_run(
                db,
                owner_id=owner,
                action_type="gateway.send",
                action_config={"body_template": "hello {who}"},
            )
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            await serialize_checkpoint(
                db,
                run=run,
                action_type="gateway.send",
                action_state={
                    "body_template": "hello {who}",
                    "body": "hello world",
                    "destination_id": "",
                    "session_key": "",
                    "event_payload": {"who": "world"},
                },
                pause_reason="contract_violation",
                contract_snapshot={
                    "allowed_tools": None,
                    "max_compute_tier": 0,
                },
            )
            await db.commit()

        async with session_maker() as db:
            cp = await hydrate_checkpoint(db, run_id=run_id)
            assert cp is not None
            result = await resume_run(db, checkpoint=cp)
            await db.commit()

        async with session_maker() as db:
            final = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
        return result, final

    result, final = asyncio.run(go())
    assert result.status == DispatchStatus.SUCCEEDED
    assert final.status == "succeeded"
    # Exactly one XADD into the gateway delivery stream.
    assert len(stub_redis.xadds) == 1


# ---------------------------------------------------------------------------
# Tests: agent paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resume_agent_continue_re_enqueues_with_message_history(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """``agent.run`` resume with no in-flight non-serializable tools re-enqueues
    ``execute_agent_task`` with the saved message_history."""
    from app.models_automations import AutomationRun
    from app.services.automations import (
        resume_run,
        serialize_checkpoint,
        hydrate_checkpoint,
    )
    from app.services.automations.checkpoint import ResumeStrategy

    saved_history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            _, run_id = await _seed_paused_run(
                db,
                owner_id=owner,
                action_type="agent.run",
                action_config={"message": "go", "model_name": "claude"},
            )
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            await serialize_checkpoint(
                db,
                run=run,
                action_type="agent.run",
                action_state={
                    "message": "go",
                    "message_history": saved_history,
                    "tool_result_trail": [],
                    "current_step": 2,
                    "in_flight_non_serializable_tools": [],
                    "agent_id": None,
                    "model_name": "claude",
                    "view_context": None,
                },
                pause_reason="tool_disallowed",
                contract_snapshot={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                },
            )
            await db.commit()

        async with session_maker() as db:
            cp = await hydrate_checkpoint(db, run_id=run_id)
            assert cp is not None
            assert cp.resume_strategy == ResumeStrategy.AGENT_CONTINUE
            await resume_run(db, checkpoint=cp)
            await db.commit()

        async with session_maker() as db:
            final = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
        return final

    final = asyncio.run(go())
    # Status is 'running' — the agent worker owns the terminal transition.
    assert final.status == "running"
    # Exactly one enqueue, payload contains the saved history.
    assert len(stub_queue.calls) == 1
    name, args, _kwargs = stub_queue.calls[0]
    assert name == "execute_agent_task"
    payload = args[0]
    assert payload["resume"] is True
    assert payload["resume_strategy"] == "agent_continue"
    assert payload["message_history"] == saved_history
    assert payload["current_step"] == 2


@pytest.mark.unit
def test_resume_agent_restart_drops_history(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """``agent.run`` resume with a non-serializable in-flight tool restarts
    the loop fresh — payload omits message_history / tool_result_trail."""
    from app.models_automations import AutomationRun
    from app.services.automations import (
        resume_run,
        serialize_checkpoint,
        hydrate_checkpoint,
    )
    from app.services.automations.checkpoint import ResumeStrategy

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            _, run_id = await _seed_paused_run(
                db,
                owner_id=owner,
                action_type="agent.run",
                action_config={"message": "go"},
            )
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            await serialize_checkpoint(
                db,
                run=run,
                action_type="agent.run",
                action_state={
                    "message": "go",
                    "message_history": [{"role": "user", "content": "x"}],
                    "tool_result_trail": [],
                    "current_step": 1,
                    "in_flight_non_serializable_tools": ["live_browser_session"],
                },
                pause_reason="tool_disallowed",
                contract_snapshot={
                    "allowed_tools": [],
                    "max_compute_tier": 0,
                },
            )
            await db.commit()

        async with session_maker() as db:
            cp = await hydrate_checkpoint(db, run_id=run_id)
            assert cp is not None
            assert cp.resume_strategy == ResumeStrategy.RESTART_FROM_CHECKPOINT
            await resume_run(db, checkpoint=cp)
            await db.commit()

    asyncio.run(go())
    assert len(stub_queue.calls) == 1
    name, args, _kwargs = stub_queue.calls[0]
    assert name == "execute_agent_task"
    payload = args[0]
    assert payload["resume"] is True
    assert payload["resume_strategy"] == "restart_from_checkpoint"
    # The restart payload deliberately omits message_history.
    assert "message_history" not in payload
    assert "tool_result_trail" not in payload


# ---------------------------------------------------------------------------
# Tests: terminal-state guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resume_run_noop_when_run_terminal(
    session_maker,
    stub_queue: _StubQueue,
    stub_redis: _StubRedis,
) -> None:
    """A terminal run should not re-enter the dispatcher (concurrent admin
    cleanup safety)."""
    from app.models_automations import AutomationRun
    from app.services.automations import (
        DispatchStatus,
        resume_run,
        serialize_checkpoint,
        hydrate_checkpoint,
    )

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            _, run_id = await _seed_paused_run(
                db,
                owner_id=owner,
                action_type="gateway.send",
                action_config={"body": "x"},
            )
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            await serialize_checkpoint(
                db,
                run=run,
                action_type="gateway.send",
                action_state={
                    "body": "x",
                    "destination_id": "",
                    "session_key": "",
                    "event_payload": {},
                },
                pause_reason="contract_violation",
                contract_snapshot={"allowed_tools": None, "max_compute_tier": 0},
            )
            run.status = "cancelled"
            await db.commit()

        async with session_maker() as db:
            cp = await hydrate_checkpoint(db, run_id=run_id)
            assert cp is not None
            return await resume_run(db, checkpoint=cp)

    result = asyncio.run(go())
    assert result.status == DispatchStatus.NOOP_TERMINAL
    assert result.run_status == "cancelled"
    # No XADD happened — the terminal guard fires before re-dispatch.
    assert len(stub_redis.xadds) == 0
