"""Phase 2 Wave 2A — unit tests for ``services.automations.checkpoint``.

The module is database-light (just one column on ``automation_runs``) but
load-bearing — every approval-driven pause goes through it. Tests cover:

* Round-trip: serialize → persist → hydrate yields a value-equal
  :class:`RunCheckpoint`.
* :func:`determine_resume_strategy` decision matrix across all three
  action types and the in_flight_non_serializable_tools toggle.
* Defensive fallbacks: malformed JSON / missing column / unknown action
  type.

Mirrors the SQLite-migration fixture pattern from ``test_dispatcher.py`` so
the real ``automation_runs.checkpoint`` JSON column is exercised, not a
mock.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration fixture (mirrors test_dispatcher.py)
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
    db_path = tmp_path / "checkpoint.db"
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
# Seed helpers (kept local to avoid cross-file import gymnastics)
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"checkpoint-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Checkpoint Test",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_run(db, *, owner_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models_automations import AutomationDefinition, AutomationRun

    automation_id = uuid.uuid4()
    db.add(
        AutomationDefinition(
            id=automation_id,
            name="cp-test",
            owner_user_id=owner_id,
            workspace_scope="none",
            contract={
                "allowed_tools": ["read_file"],
                "max_compute_tier": 0,
            },
            max_compute_tier=0,
        )
    )
    run_id = uuid.uuid4()
    db.add(
        AutomationRun(
            id=run_id,
            automation_id=automation_id,
            event_id=None,
            status="running",
            spend_usd=Decimal("0.05"),
        )
    )
    await db.flush()
    return automation_id, run_id


# ---------------------------------------------------------------------------
# determine_resume_strategy: decision matrix
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_determine_strategy_app_invoke_always_redispatch() -> None:
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        determine_resume_strategy,
    )

    assert (
        determine_resume_strategy("app.invoke", {}, {})
        == ResumeStrategy.REDISPATCH
    )
    assert (
        determine_resume_strategy(
            "app.invoke", {"in_flight_non_serializable_tools": ["bash"]}, {}
        )
        == ResumeStrategy.REDISPATCH
    )


@pytest.mark.unit
def test_determine_strategy_gateway_send_always_redispatch() -> None:
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        determine_resume_strategy,
    )

    assert (
        determine_resume_strategy("gateway.send", {}, {})
        == ResumeStrategy.REDISPATCH
    )


@pytest.mark.unit
def test_determine_strategy_agent_clean_continues() -> None:
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        determine_resume_strategy,
    )

    assert (
        determine_resume_strategy(
            "agent.run",
            {"in_flight_non_serializable_tools": []},
            {},
        )
        == ResumeStrategy.AGENT_CONTINUE
    )


@pytest.mark.unit
def test_determine_strategy_agent_with_non_serializable_restarts() -> None:
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        determine_resume_strategy,
    )

    assert (
        determine_resume_strategy(
            "agent.run",
            {"in_flight_non_serializable_tools": ["live_browser_session"]},
            {},
        )
        == ResumeStrategy.RESTART_FROM_CHECKPOINT
    )


@pytest.mark.unit
def test_determine_strategy_unknown_action_falls_back_to_restart() -> None:
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        determine_resume_strategy,
    )

    assert (
        determine_resume_strategy("mystery.kind", {}, {})
        == ResumeStrategy.RESTART_FROM_CHECKPOINT
    )


# ---------------------------------------------------------------------------
# Round-trip: serialize → persist → hydrate
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialize_then_hydrate_round_trip_app_invoke(session_maker) -> None:
    """An app.invoke checkpoint survives a round-trip through JSONB."""
    from app.models_automations import AutomationRun
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        hydrate_checkpoint,
        serialize_checkpoint,
    )

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            automation_id, run_id = await _seed_run(db, owner_id=owner)
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            cp = await serialize_checkpoint(
                db,
                run=run,
                action_type="app.invoke",
                action_state={
                    "input": {"target": "billing.charge"},
                    "app_action_id": str(uuid.uuid4()),
                    "partial_output": None,
                },
                pause_reason="budget_exceeded",
                contract_snapshot={
                    "allowed_tools": ["invoke_app_action"],
                    "max_compute_tier": 0,
                },
                budget_allocation={
                    "litellm_key_id": "sk-id-1",
                    "litellm_key_value": "sk-secret",
                    "max_usd_per_run": Decimal("1.50"),
                    "daily_remaining_usd": Decimal("12.00"),
                    "is_extension": False,
                },
            )
            await db.commit()

        async with session_maker() as db:
            loaded = await hydrate_checkpoint(db, run_id=run_id)

        return cp, loaded

    cp, loaded = asyncio.run(go())
    assert loaded is not None
    assert loaded.run_id == cp.run_id
    assert loaded.automation_id == cp.automation_id
    assert loaded.action_type == "app.invoke"
    assert loaded.resume_strategy == ResumeStrategy.REDISPATCH
    assert loaded.pause_reason == "budget_exceeded"
    assert loaded.action_state["input"] == {"target": "billing.charge"}
    # Decimals serialize as strings on the JSON side; compare semantically.
    assert loaded.budget_allocation is not None
    assert loaded.budget_allocation["litellm_key_id"] == "sk-id-1"
    assert Decimal(loaded.budget_allocation["max_usd_per_run"]) == Decimal("1.50")


@pytest.mark.unit
def test_serialize_marks_agent_run_with_non_serializable_as_restart(
    session_maker,
) -> None:
    """The dispatcher pre-fills in_flight_non_serializable_tools; the
    serializer surfaces it as resume_strategy=restart_from_checkpoint."""
    from app.models_automations import AutomationRun
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        hydrate_checkpoint,
        serialize_checkpoint,
    )

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            automation_id, run_id = await _seed_run(db, owner_id=owner)
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
                    "message_history": [{"role": "user", "content": "hi"}],
                    "tool_result_trail": [],
                    "current_step": 3,
                    "in_flight_non_serializable_tools": ["bash_session"],
                },
                pause_reason="tool_disallowed",
                contract_snapshot={"allowed_tools": [], "max_compute_tier": 0},
            )
            await db.commit()

        async with session_maker() as db:
            return await hydrate_checkpoint(db, run_id=run_id)

    loaded = asyncio.run(go())
    assert loaded is not None
    assert loaded.resume_strategy == ResumeStrategy.RESTART_FROM_CHECKPOINT
    assert loaded.action_state["in_flight_non_serializable_tools"] == [
        "bash_session"
    ]


@pytest.mark.unit
def test_serialize_clean_agent_run_marks_continue(session_maker) -> None:
    from app.models_automations import AutomationRun
    from app.services.automations.checkpoint import (
        ResumeStrategy,
        hydrate_checkpoint,
        serialize_checkpoint,
    )

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            automation_id, run_id = await _seed_run(db, owner_id=owner)
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
                    "message_history": [],
                    "tool_result_trail": [],
                    "current_step": 0,
                    "in_flight_non_serializable_tools": [],
                },
                pause_reason="budget_exceeded",
                contract_snapshot={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                },
            )
            await db.commit()

        async with session_maker() as db:
            return await hydrate_checkpoint(db, run_id=run_id)

    loaded = asyncio.run(go())
    assert loaded is not None
    assert loaded.resume_strategy == ResumeStrategy.AGENT_CONTINUE


@pytest.mark.unit
def test_hydrate_returns_none_when_no_checkpoint(session_maker) -> None:
    from app.services.automations.checkpoint import hydrate_checkpoint

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            _, run_id = await _seed_run(db, owner_id=owner)
            await db.commit()

        async with session_maker() as db:
            return await hydrate_checkpoint(db, run_id=run_id)

    result = asyncio.run(go())
    assert result is None


@pytest.mark.unit
def test_hydrate_returns_none_for_missing_run(session_maker) -> None:
    """Hydrating a non-existent run id is a no-op (None) — the resume worker
    treats this as 'nothing to do' and does not raise."""
    from app.services.automations.checkpoint import hydrate_checkpoint

    async def go():
        async with session_maker() as db:
            return await hydrate_checkpoint(db, run_id=uuid.uuid4())

    assert asyncio.run(go()) is None


@pytest.mark.unit
def test_serialize_rejects_unknown_action_type(session_maker) -> None:
    from app.models_automations import AutomationRun
    from app.services.automations.checkpoint import serialize_checkpoint

    async def go():
        async with session_maker() as db:
            owner = await _seed_user(db)
            _, run_id = await _seed_run(db, owner_id=owner)
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            with pytest.raises(ValueError, match="action_type"):
                await serialize_checkpoint(
                    db,
                    run=run,
                    action_type="bogus.kind",
                    action_state={},
                    pause_reason="x",
                )

    asyncio.run(go())
