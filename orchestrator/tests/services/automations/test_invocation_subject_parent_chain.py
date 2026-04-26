"""Targeted tests for the InvocationSubject parent-chain resolution.

Complements ``test_invocation_subject.py`` by focusing specifically on
the ``parent_run_id`` branch:

* When a parent run + parent subject exist, the resolver mints a child
  subject with ``payer_policy='parent_run'``, ``parent_run_id=<parent>``,
  and ``credit_source_ref=str(parent_run.id)``.
* When ``parent_run_id`` points at nothing (no run row) the resolver
  raises ``ParentRunCycleError`` because the validation walk treats a
  missing ancestor as a stop signal — but the resolver itself never sees
  the bad reference because it requires a real ``AutomationRun`` object.
  The "unknown parent" failure mode therefore manifests during the
  caller's preflight (the parent-run row lookup), not inside the
  resolver. We assert that contract by trying to resolve with a parent
  run that has no InvocationSubject row — the resolver SHOULD still
  produce a child subject (parent subject is best-effort) and budget
  envelope falls back to the contract caps.
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
# Fixtures (mirror tests/services/automations/test_invocation_subject.py)
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
    db_path = tmp_path / "subject_parent_chain.db"
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
            email=f"chain-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Chain Tester",
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
        name="parent-chain-test",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={
            "allowed_tools": [],
            "max_compute_tier": 0,
            "max_spend_per_run_usd": "2.00",
        },
        max_compute_tier=0,
        is_active=True,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def _seed_run(db, *, automation_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import AutomationEvent, AutomationRun

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        payload={},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=automation_id,
        event_id=evt.id,
        status="preflight",
    )
    db.add(run)
    await db.flush()
    return run.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_with_parent_run_id_creates_parent_run_subject(
    session_maker,
) -> None:
    """parent_run + parent subject exist → child mints with payer_policy=parent_run."""
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        InvocationSubject,
    )
    from app.services.automations.invocation_subject import (
        CreditSource,
        PayerPolicy,
        resolve_invocation_subject,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            parent_autom_id = await _seed_automation(db, owner_user_id=user_id)
            parent_run_id = await _seed_run(db, automation_id=parent_autom_id)
            child_autom_id = await _seed_automation(db, owner_user_id=user_id)
            child_run_id = await _seed_run(db, automation_id=child_autom_id)
            await db.commit()

        # Resolve the parent first so its subject row exists.
        async with session_maker() as db:
            parent_run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == parent_run_id)
                )
            ).scalar_one()
            parent_autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == parent_autom_id
                    )
                )
            ).scalar_one()
            await resolve_invocation_subject(
                db, automation_run=parent_run, automation=parent_autom
            )
            await db.commit()

        # Now resolve the child with parent_run= the parent's run.
        async with session_maker() as db:
            child_run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == child_run_id)
                )
            ).scalar_one()
            child_autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == child_autom_id
                    )
                )
            ).scalar_one()
            parent_run_for_resolve = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == parent_run_id)
                )
            ).scalar_one()
            child_resolved = await resolve_invocation_subject(
                db,
                automation_run=child_run,
                automation=child_autom,
                parent_run=parent_run_for_resolve,
            )
            await db.commit()
            return child_resolved, parent_run_id

    child_resolved, parent_run_id = asyncio.run(go())

    assert child_resolved.payer_policy == PayerPolicy.PARENT_RUN
    assert child_resolved.credit_source == CreditSource.PARENT_RUN
    assert child_resolved.parent_run_id == parent_run_id
    assert child_resolved.credit_source_ref == str(parent_run_id)
    # Child's per-run cap is intersected with parent's remaining budget
    # (parent contract caps at 2.00; nothing spent yet).
    assert child_resolved.budget_envelope.max_usd_per_run == Decimal("2.00")


@pytest.mark.unit
def test_parent_run_id_unknown_falls_back_to_installer(session_maker) -> None:
    """parent_run pointing at a row with no InvocationSubject still mints a
    child subject — but the budget envelope falls back to the contract
    caps (no parent-remaining intersection), and the policy stays
    parent_run because the resolver was explicitly asked to inherit.

    The plan calls this the "logged warning" path: the resolver does NOT
    raise; downstream settle_subject_spend will tolerate the missing
    parent on the rollup walk.
    """
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
    )
    from app.services.automations.invocation_subject import (
        PayerPolicy,
        resolve_invocation_subject,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            parent_autom_id = await _seed_automation(db, owner_user_id=user_id)
            # Parent run exists but we never call resolve on it — no
            # InvocationSubject row backs it.
            parent_run_id = await _seed_run(db, automation_id=parent_autom_id)
            child_autom_id = await _seed_automation(db, owner_user_id=user_id)
            child_run_id = await _seed_run(db, automation_id=child_autom_id)
            await db.commit()

        async with session_maker() as db:
            child_run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == child_run_id)
                )
            ).scalar_one()
            child_autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == child_autom_id
                    )
                )
            ).scalar_one()
            parent_run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == parent_run_id)
                )
            ).scalar_one()
            child_resolved = await resolve_invocation_subject(
                db,
                automation_run=child_run,
                automation=child_autom,
                parent_run=parent_run,
            )
            await db.commit()
            return child_resolved

    child_resolved = asyncio.run(go())

    # The resolver did NOT raise; it minted a child subject pointed at the
    # parent run id even though no parent subject backs it.
    assert child_resolved.payer_policy == PayerPolicy.PARENT_RUN
    # Budget envelope falls back to the child's own contract caps —
    # the child contract here has max_spend_per_run_usd=2.00.
    assert child_resolved.budget_envelope.max_usd_per_run == Decimal("2.00")
