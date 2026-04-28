"""Phase 1 — unit tests for ``services.gateway.scheduler.cron_tick``.

The scheduler is the cron Producer side of the Automation Runtime split:
it claims due ``automation_triggers(kind='cron')`` rows, advances
``next_run_at``, materializes ``AutomationEvent`` + ``AutomationRun``
records in one transaction, then enqueues
``dispatch_automation_task`` to ARQ.

Tests run against a real SQLite database upgraded to alembic ``head`` so
the actual ``automation_*`` schema (with its constraints) is in play.
We stub the ARQ pool so we can introspect the enqueue calls without a
running Redis.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# SQLite migration fixture (mirrors tests/services/automations/test_dispatcher.py)
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
    db_path = tmp_path / "scheduler.db"
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
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"sched-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Sched User",
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
    is_active: bool = True,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="cron-test-automation",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={
            "allowed_tools": [],
            "max_compute_tier": 0,
            "on_breach": "pause_for_approval",
        },
        max_compute_tier=0,
        is_active=is_active,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def _seed_cron_trigger(
    db,
    *,
    automation_id: uuid.UUID,
    cron_expression: str | None = "*/5 * * * *",
    timezone: str | None = "UTC",
    next_run_at: datetime | None = None,
    is_active: bool = True,
) -> uuid.UUID:
    from app.models_automations import AutomationTrigger

    cfg: dict[str, Any] = {}
    if cron_expression is not None:
        cfg["cron_expression"] = cron_expression
    if timezone is not None:
        cfg["timezone"] = timezone

    trig = AutomationTrigger(
        id=uuid.uuid4(),
        automation_id=automation_id,
        kind="cron",
        config=cfg,
        next_run_at=next_run_at,
        is_active=is_active,
    )
    db.add(trig)
    await db.flush()
    return trig.id


# ---------------------------------------------------------------------------
# Stub ARQ pool — captures enqueue_job calls.
# ---------------------------------------------------------------------------


class _StubArqPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))

        class _Job:
            job_id = f"job-{uuid.uuid4().hex[:8]}"

        return _Job()


class _BoomArqPool:
    """Pool whose enqueue always raises — exercises the recovery path."""

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated redis failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cron_tick_no_due_triggers_returns_zero(session_maker) -> None:
    """No due rows → returns 0, no enqueues, no inserts."""
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            # Trigger scheduled far in the future.
            future = datetime.now(UTC) + timedelta(days=7)
            await _seed_cron_trigger(
                db, automation_id=automation_id, next_run_at=future
            )
            await db.commit()

        async with session_maker() as db:
            return await cron_tick(db, pool)

    fired = asyncio.run(go())
    assert fired == 0
    assert pool.calls == []


@pytest.mark.unit
def test_cron_tick_fires_due_trigger_and_advances_next_run_at(
    session_maker,
) -> None:
    """One due trigger → AutomationEvent only (dispatcher creates the run) + 1 enqueue."""
    from app.models_automations import (
        AutomationEvent,
        AutomationRun,
        AutomationTrigger,
    )
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            # next_run_at in the past → due now.
            past = datetime.now(UTC) - timedelta(minutes=10)
            trigger_id = await _seed_cron_trigger(
                db,
                automation_id=automation_id,
                cron_expression="*/5 * * * *",
                next_run_at=past,
            )
            await db.commit()
            return automation_id, trigger_id

        return None  # pragma: no cover

    automation_id, trigger_id = asyncio.run(go())

    async def tick_and_assert():
        now = datetime.now(UTC)
        async with session_maker() as db:
            fired = await cron_tick(db, pool, now=now)
        assert fired == 1
        assert len(pool.calls) == 1
        name, args, kwargs = pool.calls[0]
        assert name == "dispatch_automation_task"
        assert args[0] == str(automation_id)
        # args[1] is the new event id; args[2] is the worker tag.
        assert args[2] == "cron-tick"
        # Job id MUST equal the event id for ARQ-side idempotency.
        assert kwargs["_job_id"] == args[1]

        async with session_maker() as db:
            events = (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.automation_id == automation_id
                    )
                )
            ).scalars().all()
            assert len(events) == 1
            evt = events[0]
            assert evt.trigger_kind == "cron"
            assert evt.trigger_id == trigger_id
            assert evt.payload.get("cron_expression") == "*/5 * * * *"
            assert str(evt.id) == args[1]

            # Cron does NOT pre-create the run row. The dispatcher's
            # _upsert_run is the sole creator of run rows for every trigger
            # source. See services/automations/sweep_on_acquire.py for the
            # event-anchored recovery contract.
            runs = (
                await db.execute(
                    select(AutomationRun).where(
                        AutomationRun.automation_id == automation_id
                    )
                )
            ).scalars().all()
            assert runs == []

            trig = (
                await db.execute(
                    select(AutomationTrigger).where(
                        AutomationTrigger.id == trigger_id
                    )
                )
            ).scalar_one()
            # next_run_at advanced past `now`; last_run_at was stamped.
            assert trig.next_run_at is not None
            assert trig.next_run_at > now
            assert trig.last_run_at is not None

    asyncio.run(tick_and_assert())


@pytest.mark.unit
def test_cron_tick_skips_inactive_definition(session_maker) -> None:
    """Trigger is_active but parent definition is_active=False → skipped."""
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db, owner_user_id=user_id, is_active=False
            )
            past = datetime.now(UTC) - timedelta(minutes=10)
            await _seed_cron_trigger(
                db, automation_id=automation_id, next_run_at=past
            )
            await db.commit()

        async with session_maker() as db:
            return await cron_tick(db, pool)

    assert asyncio.run(go()) == 0
    assert pool.calls == []


@pytest.mark.unit
def test_cron_tick_malformed_cron_deactivates_trigger(session_maker) -> None:
    """Bad cron expression → trigger deactivated, no event/run, no crash."""
    from app.models_automations import (
        AutomationEvent,
        AutomationRun,
        AutomationTrigger,
    )
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            past = datetime.now(UTC) - timedelta(minutes=10)
            trigger_id = await _seed_cron_trigger(
                db,
                automation_id=automation_id,
                cron_expression="this is not a cron expr",
                next_run_at=past,
            )
            await db.commit()
            return automation_id, trigger_id

    automation_id, trigger_id = asyncio.run(go())

    async def tick_and_assert():
        async with session_maker() as db:
            fired = await cron_tick(db, pool)
        assert fired == 0
        assert pool.calls == []

        async with session_maker() as db:
            trig = (
                await db.execute(
                    select(AutomationTrigger).where(
                        AutomationTrigger.id == trigger_id
                    )
                )
            ).scalar_one()
            assert trig.is_active is False

            events = (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.automation_id == automation_id
                    )
                )
            ).scalars().all()
            assert events == []
            runs = (
                await db.execute(
                    select(AutomationRun).where(
                        AutomationRun.automation_id == automation_id
                    )
                )
            ).scalars().all()
            assert runs == []

    asyncio.run(tick_and_assert())


@pytest.mark.unit
def test_cron_tick_missing_expression_deactivates(session_maker) -> None:
    """Trigger config missing both cron_expression/expression → deactivated."""
    from app.models_automations import AutomationTrigger
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            past = datetime.now(UTC) - timedelta(minutes=10)
            trigger_id = await _seed_cron_trigger(
                db,
                automation_id=automation_id,
                cron_expression=None,
                timezone=None,
                next_run_at=past,
            )
            await db.commit()
            return trigger_id

    trigger_id = asyncio.run(go())

    async def tick_and_assert():
        async with session_maker() as db:
            fired = await cron_tick(db, pool)
        assert fired == 0
        assert pool.calls == []

        async with session_maker() as db:
            trig = (
                await db.execute(
                    select(AutomationTrigger).where(
                        AutomationTrigger.id == trigger_id
                    )
                )
            ).scalar_one()
            assert trig.is_active is False

    asyncio.run(tick_and_assert())


@pytest.mark.unit
def test_cron_tick_invalid_timezone_deactivates(session_maker) -> None:
    """Trigger config has unknown timezone → deactivated, no fire."""
    from app.models_automations import AutomationTrigger
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            past = datetime.now(UTC) - timedelta(minutes=10)
            trigger_id = await _seed_cron_trigger(
                db,
                automation_id=automation_id,
                cron_expression="*/5 * * * *",
                timezone="Mars/Olympus_Mons",
                next_run_at=past,
            )
            await db.commit()
            return trigger_id

    trigger_id = asyncio.run(go())

    async def tick_and_assert():
        async with session_maker() as db:
            fired = await cron_tick(db, pool)
        assert fired == 0
        assert pool.calls == []

        async with session_maker() as db:
            trig = (
                await db.execute(
                    select(AutomationTrigger).where(
                        AutomationTrigger.id == trigger_id
                    )
                )
            ).scalar_one()
            assert trig.is_active is False

    asyncio.run(tick_and_assert())


@pytest.mark.unit
def test_cron_tick_enqueue_failure_leaves_event_undispatched(session_maker) -> None:
    """If ARQ enqueue fails, the AutomationEvent row stays undispatched.

    The producer is no longer responsible for creating the run row — the
    dispatcher's ``_upsert_run`` is the sole creator. Recovery is anchored
    on the event row instead: ``sweep_on_acquire`` and ``missed_event_drain``
    re-enqueue events with ``dispatched_at IS NULL`` past the stale cutoff.
    """
    from app.models_automations import AutomationEvent, AutomationRun
    from app.services.gateway.scheduler import cron_tick

    boom = _BoomArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            past = datetime.now(UTC) - timedelta(minutes=10)
            await _seed_cron_trigger(
                db, automation_id=automation_id, next_run_at=past
            )
            await db.commit()
            return automation_id

    automation_id = asyncio.run(go())

    async def tick_and_assert():
        async with session_maker() as db:
            fired = await cron_tick(db, boom)
        # Enqueue failed → no jobs counted as fired.
        assert fired == 0

        async with session_maker() as db:
            # Event was committed before the (failed) enqueue, so it
            # exists with dispatched_at IS NULL — the sweep's recovery
            # anchor.
            events = (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.automation_id == automation_id
                    )
                )
            ).scalars().all()
            assert len(events) == 1
            assert events[0].dispatched_at is None

            # No run row — the dispatcher never executed.
            runs = (
                await db.execute(
                    select(AutomationRun).where(
                        AutomationRun.automation_id == automation_id
                    )
                )
            ).scalars().all()
            assert runs == []

    asyncio.run(tick_and_assert())


@pytest.mark.unit
def test_cron_tick_concurrent_sessions_each_claim_distinct_rows(
    session_maker,
) -> None:
    """Two parallel session contexts must NOT both claim the same trigger.

    Postgres uses ``SELECT ... FOR UPDATE SKIP LOCKED`` to enforce this; on
    SQLite (this test) the same correctness comes from session-level
    serialization. Either way, the union of claims must equal the set of
    due triggers and no trigger may fire twice (UNIQUE constraint on
    ``automation_runs(automation_id, event_id)`` would catch a double-fire
    even if the claim races).
    """
    from app.models_automations import AutomationEvent, AutomationRun
    from app.services.gateway.scheduler import cron_tick

    pool_a = _StubArqPool()
    pool_b = _StubArqPool()

    async def go():
        # Seed 4 due triggers across 4 distinct automations.
        async with session_maker() as db:
            user_id = await _seed_user(db)
            past = datetime.now(UTC) - timedelta(minutes=10)
            automation_ids = []
            for _ in range(4):
                automation_id = await _seed_automation(db, owner_user_id=user_id)
                await _seed_cron_trigger(
                    db, automation_id=automation_id, next_run_at=past
                )
                automation_ids.append(automation_id)
            await db.commit()

        # Race two ticks — they share nothing except the underlying DB.
        async def one(pool):
            async with session_maker() as db:
                return await cron_tick(db, pool)

        a, b = await asyncio.gather(one(pool_a), one(pool_b))
        return automation_ids, a, b

    automation_ids, a, b = asyncio.run(go())

    # Each trigger fires at most once → total enqueues ≤ rows seeded.
    assert a + b <= len(automation_ids)
    assert a + b == len(pool_a.calls) + len(pool_b.calls)

    async def assert_no_double_fire():
        async with session_maker() as db:
            for automation_id in automation_ids:
                evts = (
                    await db.execute(
                        select(AutomationEvent).where(
                            AutomationEvent.automation_id == automation_id
                        )
                    )
                ).scalars().all()
                assert len(evts) <= 1, (
                    f"automation {automation_id} fired {len(evts)} times"
                )
                runs = (
                    await db.execute(
                        select(AutomationRun).where(
                            AutomationRun.automation_id == automation_id
                        )
                    )
                ).scalars().all()
                assert len(runs) <= 1

    asyncio.run(assert_no_double_fire())


@pytest.mark.unit
def test_cron_tick_null_next_run_at_treated_as_due(session_maker) -> None:
    """next_run_at IS NULL must be picked up (first-time scheduling)."""
    from app.services.gateway.scheduler import cron_tick

    pool = _StubArqPool()

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            await _seed_cron_trigger(
                db, automation_id=automation_id, next_run_at=None
            )
            await db.commit()

        async with session_maker() as db:
            return await cron_tick(db, pool)

    assert asyncio.run(go()) == 1
    assert len(pool.calls) == 1
