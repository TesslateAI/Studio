"""Controller-plane lease + intent failover (demo flow #16).

Two surfaces under test:

1. **Lease takeover** — node-A holds the ``controller`` lease, then
   crashes. node-B's ``acquire`` MUST bump ``term``. The on-acquire
   sweep then re-enqueues every queued run that's older than the
   stale-cutoff (the dispatcher's UNIQUE constraint + ARQ ``_job_id``
   dedup are the safety nets that make this idempotent).

2. **Intent reconciler fencing** — a ``ControllerIntent`` written under
   a stale lease term must be marked ``superseded`` instead of touching
   K8s. A fresh intent under the current term must drive the K8s patch
   call exactly once.

Parametrized over the lease backend so the same contract is verified
for every implementation. Today only ``db`` is in the matrix; ``redis``
is added when the Redis test fixture lands (see deferral note in the
agent report).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
    db_path = tmp_path / "controller_failover.db"
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
def session_maker(migrated_sqlite: str, monkeypatch: pytest.MonkeyPatch):
    """Sessionmaker that ALSO patches ``app.database.AsyncSessionLocal``.

    The DB lease backend opens its own session via
    ``AsyncSessionLocal`` -- without the monkeypatch the lease would
    talk to the default Postgres URL instead of our migrated SQLite.
    """
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", maker, raising=False
    )

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
            email=f"failover-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Failover User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation(db, *, owner_user_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom_id = uuid.uuid4()
    db.add(
        AutomationDefinition(
            id=autom_id,
            name="failover-test",
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
    await db.flush()
    return autom_id


async def _seed_queued_run(
    db,
    *,
    automation_id: uuid.UUID,
    age_seconds: int,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert an undispatched event aged ``age_seconds`` in the past.

    The contract the sweep enforces is now event-anchored: the previous
    leader committed an :class:`AutomationEvent` but its dispatch enqueue
    was lost, so ``dispatched_at IS NULL`` past the stale cutoff. The
    dispatcher itself creates the run row on its first invocation, so we
    do NOT pre-create one here. (See ``services/automations/sweep_on_acquire.py``
    for the full contract.) The first return value stays a UUID so call
    sites that want a "queued-run identity" still get one — it's the
    ``run_id`` the dispatcher *will* mint on first dispatch — but for
    the sweep test we only assert against ``event_id``.
    """
    from app.models_automations import AutomationEvent

    past = datetime.now(UTC) - timedelta(seconds=age_seconds)
    event_id = uuid.uuid4()
    db.add(
        AutomationEvent(
            id=event_id,
            automation_id=automation_id,
            payload={},
            trigger_kind="cron",
            received_at=past,
        )
    )
    await db.flush()
    # Synthetic run_id placeholder — sweep tests assert against event_id.
    return uuid.uuid4(), event_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backend",
    ["db"],
    # TODO(integration-tests): add 'redis' once the integration test
    # harness ships a real Redis fixture. The DB backend is already
    # exercising the term-bump + sweep contract; redis just swaps the
    # storage primitive.
)
async def test_lease_failover_re_enqueues_stuck_runs(
    backend: str,
    session_maker,
) -> None:
    """node-A crash, node-B acquire bumps term, sweep re-enqueues 3 stale runs."""
    from app.services.automations.lease import get_lease_backend
    from app.services.automations.sweep_on_acquire import sweep_once

    lease = get_lease_backend(backend)

    # 1. node-A acquires the lease at term=N.
    token_a = await lease.acquire("controller", holder_id="node-A", ttl_seconds=60)
    assert token_a is not None, "node-A failed to acquire the lease"
    term_n = token_a.term

    # 2. Insert 3 queued runs aged 2 minutes -- past the 60s stale cutoff.
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        automation_id = await _seed_automation(db, owner_user_id=owner_id)
        seeded: list[tuple[uuid.UUID, uuid.UUID]] = []
        for _ in range(3):
            seeded.append(
                await _seed_queued_run(
                    db, automation_id=automation_id, age_seconds=120
                )
            )
        await db.commit()

    # 3. Simulate node-A crash: its lease entry stays but expires below.
    #    We force expiry by acquiring with an expired window.
    #    DBLease handles "expired by other" naturally on the next acquire.
    #    To force expiry we update the row directly.
    async with session_maker() as db:
        from sqlalchemy import text

        await db.execute(
            text(
                "UPDATE controller_leases SET expires_at = :past "
                "WHERE name = :name"
            ),
            {
                "past": datetime.now(UTC) - timedelta(seconds=1),
                "name": "controller",
            },
        )
        await db.commit()

    # 4. node-B acquires -- term must bump to N+1.
    token_b = await lease.acquire("controller", holder_id="node-B", ttl_seconds=60)
    assert token_b is not None, "node-B could not take over the lease"
    assert token_b.term > term_n, (
        f"lease term did not bump on takeover: N={term_n} N+1={token_b.term}"
    )

    # 5. sweep_once with a mocked ARQ pool -- assert all 3 enqueued.
    arq_pool = AsyncMock()
    arq_pool.enqueue_job = AsyncMock(return_value=None)

    fired = await sweep_once(
        db_factory=session_maker,
        arq_pool=arq_pool,
        current_term=token_b.term,
    )
    assert fired == 3, f"expected 3 sweep enqueues, got {fired}"

    # ARQ dedup belt: every call must use _job_id=str(event_id).
    seen_job_ids = {
        call.kwargs.get("_job_id") for call in arq_pool.enqueue_job.await_args_list
    }
    expected_job_ids = {str(event_id) for _, event_id in seeded}
    assert seen_job_ids == expected_job_ids, (
        f"sweep didn't pin _job_id to event_id: got {seen_job_ids} "
        f"expected {expected_job_ids}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_intent_marked_superseded_without_touching_k8s(
    session_maker,
) -> None:
    """Reconciler with current term=N+1 must mark a term=N intent superseded.

    The reconciler MUST NOT call any K8s mutation on a stale intent --
    that's the whole point of the lease-fence pattern.
    """
    from app.models_automations import ControllerIntent
    from app.services.automations.intents import reconciler

    # Stale intent (term=42) sitting pending.
    stale_intent_id = uuid.uuid4()
    async with session_maker() as db:
        db.add(
            ControllerIntent(
                id=stale_intent_id,
                kind="scale_to_zero",
                target_ref={"namespace": "proj-x", "deployment": "d"},
                lease_term=42,
                status="pending",
            )
        )
        await db.commit()

    # Reconciler runs at term=43 -- stale intent must be superseded.
    fake_recon = MagicMock()
    fake_recon.apply = AsyncMock(side_effect=AssertionError(
        "reconciler.apply MUST NOT be called for a stale-term intent"
    ))

    counts = await reconciler.tick(
        db_factory=session_maker,
        current_term=43,
        reconciler=fake_recon,
    )

    assert counts["superseded"] == 1, counts
    assert counts["applied"] == 0, counts
    fake_recon.apply.assert_not_called()

    # Verify the row's status.
    async with session_maker() as db:
        row = (
            await db.execute(
                select(ControllerIntent).where(
                    ControllerIntent.id == stale_intent_id
                )
            )
        ).scalar_one()
    assert row.status == "superseded"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_current_term_intent_drives_single_k8s_patch(
    session_maker,
) -> None:
    """A current-term scale_to_zero intent applies once and lands ``applied``."""
    from app.models_automations import ControllerIntent
    from app.services.automations.intents import reconciler

    intent_id = uuid.uuid4()
    target_ref = {
        "namespace": "proj-foo",
        "deployment": "frontend",
        "replicas": 0,
    }
    async with session_maker() as db:
        db.add(
            ControllerIntent(
                id=intent_id,
                kind="scale_to_zero",
                target_ref=target_ref,
                lease_term=99,
                status="pending",
            )
        )
        await db.commit()

    fake_recon = MagicMock()
    fake_recon.apply = AsyncMock(return_value=None)

    counts = await reconciler.tick(
        db_factory=session_maker,
        current_term=99,
        reconciler=fake_recon,
    )
    assert counts["applied"] == 1, counts
    fake_recon.apply.assert_awaited_once_with("scale_to_zero", target_ref)

    async with session_maker() as db:
        row = (
            await db.execute(
                select(ControllerIntent).where(
                    ControllerIntent.id == intent_id
                )
            )
        ).scalar_one()
    assert row.status == "applied"
    assert row.applied_at is not None
    assert row.applied_by_term == 99
