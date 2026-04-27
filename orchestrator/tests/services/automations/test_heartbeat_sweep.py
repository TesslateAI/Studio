"""Phase 4 — heartbeat sweep tests.

Exercises :func:`app.services.automations.heartbeat_sweep.sweep_stale_running`:

* no eligible rows → returns 0
* eligible row, retry_count below cap → row flips to ``expired``,
  retry_count incremented, and a fresh ``dispatch_automation_task`` is
  enqueued with ``_job_id=str(run_id)``.
* eligible row already at cap → row flips terminal ``failed`` with
  ``paused_reason='exhausted_retries'`` and NOTHING is enqueued.

Uses the alembic-migrated SQLite pattern from
``test_cron_producer.py`` so the real DB schema (CHECK constraints,
defaults, FKs) is exercised.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Fixtures (mirror test_cron_producer.py)
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
    db_path = tmp_path / "heartbeat_sweep.db"
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
# Helpers
# ---------------------------------------------------------------------------


class _FakeArqPool:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))

        class _Job:
            job_id = kwargs.get("_job_id", "")

        return _Job()


async def _seed_user(maker) -> uuid.UUID:
    from sqlalchemy import insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    async with maker() as db:
        await db.execute(
            insert(User.__table__).values(
                id=user_id,
                email=f"hb-{suffix}@example.com",
                hashed_password="x",
                is_active=True,
                is_verified=True,
                is_superuser=False,
                name="HB Tester",
                username=f"u{suffix}",
                slug=f"u-{suffix}",
            )
        )
        await db.commit()
    return user_id


async def _seed_run(
    maker,
    *,
    owner_id: uuid.UUID,
    heartbeat_age_seconds: int,
    retry_count: int = 0,
    status: str = "running",
    with_event: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    """Insert a (definition, optional event, run) triple. Returns ids."""
    from app.models_automations import (
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
    )

    autom_id = uuid.uuid4()
    run_id = uuid.uuid4()
    event_id: uuid.UUID | None = uuid.uuid4() if with_event else None
    now = datetime.now(UTC)

    async with maker() as db:
        db.add(
            AutomationDefinition(
                id=autom_id,
                name=f"hb-{uuid.uuid4().hex[:6]}",
                owner_user_id=owner_id,
                workspace_scope="none",
                contract={"allowed_tools": [], "max_compute_tier": 0},
                max_compute_tier=0,
                is_active=True,
            )
        )
        await db.flush()
        if event_id is not None:
            db.add(
                AutomationEvent(
                    id=event_id,
                    automation_id=autom_id,
                    trigger_kind="manual",
                    payload={},
                    received_at=now,
                )
            )
            await db.flush()
        db.add(
            AutomationRun(
                id=run_id,
                automation_id=autom_id,
                event_id=event_id,
                status=status,
                retry_count=retry_count,
                heartbeat_at=now - timedelta(seconds=heartbeat_age_seconds),
            )
        )
        await db.commit()
    return autom_id, run_id, event_id


async def _seed_lease(maker, *, term: int) -> None:
    async with maker() as db:
        await db.execute(
            text(
                "INSERT INTO controller_leases (name, holder, term, expires_at, acquired_at) "
                "VALUES ('controller', 'test-holder', :term, :exp, :acq)"
            ),
            {
                "term": term,
                "exp": datetime.now(UTC) + timedelta(seconds=60),
                "acq": datetime.now(UTC),
            },
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_eligible_rows_returns_zero(session_maker) -> None:
    from app.services.automations.heartbeat_sweep import sweep_stale_running

    user_id = await _seed_user(session_maker)
    # Fresh heartbeat — well within the 90s cutoff.
    await _seed_run(session_maker, owner_id=user_id, heartbeat_age_seconds=5)
    await _seed_lease(session_maker, term=1)

    pool = _FakeArqPool()
    async with session_maker() as db:
        swept = await sweep_stale_running(db, queue=pool, current_term=1)
    assert swept == 0
    assert pool.calls == []


@pytest.mark.asyncio
async def test_stale_running_retries_below_cap(session_maker) -> None:
    from app.models_automations import AutomationRun
    from app.services.automations.heartbeat_sweep import sweep_stale_running

    user_id = await _seed_user(session_maker)
    autom_id, run_id, event_id = await _seed_run(
        session_maker,
        owner_id=user_id,
        heartbeat_age_seconds=300,  # well past the 90s cutoff
        retry_count=0,
    )
    await _seed_lease(session_maker, term=7)

    pool = _FakeArqPool()
    async with session_maker() as db:
        swept = await sweep_stale_running(
            db, queue=pool, current_term=7, max_retries=3
        )
    assert swept == 1

    async with session_maker() as db:
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
    assert run.status == "expired"
    assert run.paused_reason == "heartbeat_lost"
    assert run.retry_count == 1
    assert run.lease_term == 7
    assert run.ended_at is not None

    # Re-enqueued via ARQ with run_id as the dedup key.
    assert len(pool.calls) == 1
    args, kwargs = pool.calls[0]
    assert args[0] == "dispatch_automation_task"
    assert args[1] == str(autom_id)
    assert args[2] == str(event_id)
    assert kwargs["_job_id"] == str(run_id)


@pytest.mark.asyncio
async def test_stale_running_terminal_at_cap(session_maker) -> None:
    from app.models_automations import AutomationRun
    from app.services.automations.heartbeat_sweep import sweep_stale_running

    user_id = await _seed_user(session_maker)
    # retry_count=3 with max_retries=3 → after increment new=4, exceeds cap.
    _autom_id, run_id, _event_id = await _seed_run(
        session_maker,
        owner_id=user_id,
        heartbeat_age_seconds=300,
        retry_count=3,
    )
    await _seed_lease(session_maker, term=2)

    pool = _FakeArqPool()
    async with session_maker() as db:
        swept = await sweep_stale_running(
            db, queue=pool, current_term=2, max_retries=3
        )
    assert swept == 1

    async with session_maker() as db:
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
    assert run.status == "failed"
    assert run.paused_reason == "exhausted_retries"
    assert run.retry_count == 4
    assert run.ended_at is not None

    # Nothing enqueued.
    assert pool.calls == []


@pytest.mark.asyncio
async def test_stale_running_with_no_event_marked_terminal(session_maker) -> None:
    """A row missing event_id can't be re-enqueued — fail it terminally."""
    from app.models_automations import AutomationRun
    from app.services.automations.heartbeat_sweep import sweep_stale_running

    user_id = await _seed_user(session_maker)
    _autom_id, run_id, _ = await _seed_run(
        session_maker,
        owner_id=user_id,
        heartbeat_age_seconds=300,
        retry_count=0,
        with_event=False,
    )
    await _seed_lease(session_maker, term=1)

    pool = _FakeArqPool()
    async with session_maker() as db:
        swept = await sweep_stale_running(db, queue=pool, current_term=1)
    assert swept == 1
    assert pool.calls == []

    async with session_maker() as db:
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
    assert run.status == "failed"
    assert run.paused_reason == "heartbeat_lost_no_event"


@pytest.mark.asyncio
async def test_lease_lost_aborts_sweep(session_maker) -> None:
    from app.models_automations import AutomationRun
    from app.services.automations.heartbeat_sweep import sweep_stale_running
    from app.services.automations.intents import LeaseLost

    user_id = await _seed_user(session_maker)
    _autom_id, run_id, _ = await _seed_run(
        session_maker,
        owner_id=user_id,
        heartbeat_age_seconds=300,
        retry_count=0,
    )
    # Lease at term=5 but we claim term=99 → LeaseLost.
    await _seed_lease(session_maker, term=5)

    pool = _FakeArqPool()
    async with session_maker() as db:
        with pytest.raises(LeaseLost):
            await sweep_stale_running(db, queue=pool, current_term=99)

    # No mutations should have been committed.
    async with session_maker() as db:
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
    assert run.status == "running"
    assert run.retry_count == 0
    assert pool.calls == []
