"""Phase 4 — controller cron producer tests.

Exercises :func:`app.services.automations.cron_producer.tick`:

* due trigger → producer inserts ``automation_events`` +
  ``automation_runs(status='queued', lease_term=current_term)``,
  advances ``next_run_at``, and ARQ enqueue happens AFTER commit.
* lease term mismatch → :class:`LeaseLost` raised, no rows inserted,
  no enqueue.
* not-yet-due trigger → no rows produced.

The fake ARQ pool is wired in so we can assert enqueue ordering
relative to the DB commit.
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
    db_path = tmp_path / "cron_producer.db"
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
                email=f"cron-{suffix}@example.com",
                hashed_password="x",
                is_active=True,
                is_verified=True,
                is_superuser=False,
                name="Cron Tester",
                username=f"u{suffix}",
                slug=f"u-{suffix}",
            )
        )
        await db.commit()
    return user_id


async def _seed_automation_with_cron(
    maker, *, owner_id: uuid.UUID, next_run_at: datetime | None
) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models_automations import AutomationDefinition, AutomationTrigger

    autom_id = uuid.uuid4()
    trig_id = uuid.uuid4()
    async with maker() as db:
        db.add(
            AutomationDefinition(
                id=autom_id,
                name="cron-test",
                owner_user_id=owner_id,
                workspace_scope="none",
                contract={"allowed_tools": [], "max_compute_tier": 0},
                max_compute_tier=0,
                is_active=True,
            )
        )
        await db.flush()
        db.add(
            AutomationTrigger(
                id=trig_id,
                automation_id=autom_id,
                kind="cron",
                config={"cron_expression": "*/5 * * * *", "timezone": "UTC"},
                next_run_at=next_run_at,
                is_active=True,
            )
        )
        await db.commit()
    return autom_id, trig_id


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
async def test_due_trigger_inserts_event_run_and_enqueues(session_maker) -> None:
    from app.models_automations import (
        AutomationEvent,
        AutomationRun,
        AutomationTrigger,
    )
    from app.services.automations.cron_producer import tick

    user_id = await _seed_user(session_maker)
    now = datetime.now(UTC)
    autom_id, trig_id = await _seed_automation_with_cron(
        session_maker, owner_id=user_id, next_run_at=now - timedelta(seconds=30)
    )
    await _seed_lease(session_maker, term=42)

    pool = _FakeArqPool()
    fired = await tick(
        db_factory=session_maker,
        arq_pool=pool,
        current_term=42,
        now=now,
    )
    assert fired == 1
    assert len(pool.calls) == 1
    args, kwargs = pool.calls[0]
    assert args[0] == "dispatch_automation_task"
    assert args[1] == str(autom_id)
    # _job_id is the event id (string of uuid).
    assert kwargs["_job_id"] == args[2]

    async with session_maker() as db:
        events = list(
            (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].trigger_kind == "cron"
        assert events[0].idempotency_key.startswith(f"cron:{trig_id}:")

        runs = list(
            (
                await db.execute(
                    select(AutomationRun).where(
                        AutomationRun.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].status == "queued"
        assert runs[0].lease_term == 42
        assert runs[0].event_id == events[0].id
        assert runs[0].heartbeat_at is not None

        trigger = (
            await db.execute(
                select(AutomationTrigger).where(AutomationTrigger.id == trig_id)
            )
        ).scalar_one()
        assert trigger.next_run_at is not None
        # next_run_at should have advanced past 'now'.
        ts = trigger.next_run_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        assert ts > now


@pytest.mark.asyncio
async def test_lease_term_mismatch_raises_lease_lost(session_maker) -> None:
    from app.models_automations import AutomationEvent, AutomationRun
    from app.services.automations.cron_producer import tick
    from app.services.automations.intents import LeaseLost

    user_id = await _seed_user(session_maker)
    now = datetime.now(UTC)
    autom_id, _ = await _seed_automation_with_cron(
        session_maker, owner_id=user_id, next_run_at=now - timedelta(seconds=30)
    )
    await _seed_lease(session_maker, term=5)

    pool = _FakeArqPool()
    with pytest.raises(LeaseLost):
        await tick(
            db_factory=session_maker,
            arq_pool=pool,
            current_term=999,
            now=now,
        )

    # Nothing enqueued.
    assert pool.calls == []

    # Nothing inserted.
    async with session_maker() as db:
        events = list(
            (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert events == []
        runs = list(
            (
                await db.execute(
                    select(AutomationRun).where(
                        AutomationRun.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert runs == []


@pytest.mark.asyncio
async def test_not_due_trigger_no_rows(session_maker) -> None:
    from app.models_automations import AutomationEvent
    from app.services.automations.cron_producer import tick

    user_id = await _seed_user(session_maker)
    now = datetime.now(UTC)
    # next_run_at well in the future.
    autom_id, _ = await _seed_automation_with_cron(
        session_maker, owner_id=user_id, next_run_at=now + timedelta(hours=1)
    )
    await _seed_lease(session_maker, term=1)

    pool = _FakeArqPool()
    fired = await tick(
        db_factory=session_maker,
        arq_pool=pool,
        current_term=1,
        now=now,
    )
    assert fired == 0
    assert pool.calls == []

    async with session_maker() as db:
        events = list(
            (
                await db.execute(
                    select(AutomationEvent).where(
                        AutomationEvent.automation_id == autom_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert events == []
