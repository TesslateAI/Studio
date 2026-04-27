"""Phase 4 — approval-timeout sweep tests.

Exercises :func:`app.services.automations.approval_timeout_sweep.sweep_expired_approvals`:

* no eligible rows → returns 0
* eligible row → request flips to ``resolved`` with the timeout
  response payload, and parent run flips to ``failed`` with
  ``paused_reason='approval_timeout'``.
* lease term mismatch → :class:`LeaseLost` raised, no rows touched.

Uses the same alembic-migrated SQLite pattern as
``test_heartbeat_sweep.py`` so the schema is real.
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
# Fixtures (mirror test_cron_producer.py / test_heartbeat_sweep.py)
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
    db_path = tmp_path / "approval_timeout_sweep.db"
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


async def _seed_user(maker) -> uuid.UUID:
    from sqlalchemy import insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    async with maker() as db:
        await db.execute(
            insert(User.__table__).values(
                id=user_id,
                email=f"appr-{suffix}@example.com",
                hashed_password="x",
                is_active=True,
                is_verified=True,
                is_superuser=False,
                name="Approval Tester",
                username=f"u{suffix}",
                slug=f"u-{suffix}",
            )
        )
        await db.commit()
    return user_id


async def _seed_run_and_request(
    maker,
    *,
    owner_id: uuid.UUID,
    expires_in_seconds: int,
    resolved: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a (definition, run, approval-request) triple. Returns (run_id, request_id)."""
    from app.models_automations import (
        AutomationApprovalRequest,
        AutomationDefinition,
        AutomationRun,
    )

    autom_id = uuid.uuid4()
    run_id = uuid.uuid4()
    request_id = uuid.uuid4()
    now = datetime.now(UTC)

    async with maker() as db:
        db.add(
            AutomationDefinition(
                id=autom_id,
                name=f"appr-{uuid.uuid4().hex[:6]}",
                owner_user_id=owner_id,
                workspace_scope="none",
                contract={"allowed_tools": [], "max_compute_tier": 0},
                max_compute_tier=0,
                is_active=True,
            )
        )
        await db.flush()
        db.add(
            AutomationRun(
                id=run_id,
                automation_id=autom_id,
                event_id=None,
                status="waiting_approval",
                heartbeat_at=now,
            )
        )
        await db.flush()
        db.add(
            AutomationApprovalRequest(
                id=request_id,
                run_id=run_id,
                reason="contract_violation",
                expires_at=now + timedelta(seconds=expires_in_seconds),
                resolved_at=now if resolved else None,
            )
        )
        await db.commit()
    return run_id, request_id


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
    from app.services.automations.approval_timeout_sweep import (
        sweep_expired_approvals,
    )

    user_id = await _seed_user(session_maker)
    # Future expiry → not eligible.
    await _seed_run_and_request(
        session_maker, owner_id=user_id, expires_in_seconds=3600
    )
    await _seed_lease(session_maker, term=1)

    async with session_maker() as db:
        swept = await sweep_expired_approvals(db, current_term=1)
    assert swept == 0


@pytest.mark.asyncio
async def test_already_resolved_skipped(session_maker) -> None:
    from app.services.automations.approval_timeout_sweep import (
        sweep_expired_approvals,
    )

    user_id = await _seed_user(session_maker)
    # Past expiry but already resolved → not eligible.
    await _seed_run_and_request(
        session_maker, owner_id=user_id, expires_in_seconds=-300, resolved=True
    )
    await _seed_lease(session_maker, term=1)

    async with session_maker() as db:
        swept = await sweep_expired_approvals(db, current_term=1)
    assert swept == 0


@pytest.mark.asyncio
async def test_expired_request_flips_and_fails_parent(session_maker) -> None:
    from app.models_automations import (
        AutomationApprovalRequest,
        AutomationRun,
    )
    from app.services.automations.approval_timeout_sweep import (
        sweep_expired_approvals,
    )

    user_id = await _seed_user(session_maker)
    # Past expiry, still waiting on a response.
    run_id, request_id = await _seed_run_and_request(
        session_maker, owner_id=user_id, expires_in_seconds=-300
    )
    await _seed_lease(session_maker, term=4)

    async with session_maker() as db:
        swept = await sweep_expired_approvals(db, current_term=4)
    assert swept == 1

    async with session_maker() as db:
        request = (
            await db.execute(
                select(AutomationApprovalRequest).where(
                    AutomationApprovalRequest.id == request_id
                )
            )
        ).scalar_one()
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()

    assert request.resolved_at is not None
    assert request.response == {"choice": "expired", "notes": "approval_timeout"}

    assert run.status == "failed"
    assert run.paused_reason == "approval_timeout"
    assert run.ended_at is not None
    assert run.lease_term == 4


@pytest.mark.asyncio
async def test_lease_lost_aborts_sweep(session_maker) -> None:
    from app.models_automations import (
        AutomationApprovalRequest,
        AutomationRun,
    )
    from app.services.automations.approval_timeout_sweep import (
        sweep_expired_approvals,
    )
    from app.services.automations.intents import LeaseLost

    user_id = await _seed_user(session_maker)
    run_id, request_id = await _seed_run_and_request(
        session_maker, owner_id=user_id, expires_in_seconds=-300
    )
    # Lease at term=5 but we claim term=99 → LeaseLost.
    await _seed_lease(session_maker, term=5)

    async with session_maker() as db:
        with pytest.raises(LeaseLost):
            await sweep_expired_approvals(db, current_term=99)

    # No mutations should have been committed.
    async with session_maker() as db:
        request = (
            await db.execute(
                select(AutomationApprovalRequest).where(
                    AutomationApprovalRequest.id == request_id
                )
            )
        ).scalar_one()
        run = (
            await db.execute(select(AutomationRun).where(AutomationRun.id == run_id))
        ).scalar_one()
    assert request.resolved_at is None
    assert request.response is None
    assert run.status == "waiting_approval"
