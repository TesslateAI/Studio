"""Phase 4 — intent-producing idle reaper tests.

Exercises :func:`app.services.apps.idle_reaper.reap_idle_runtimes`:

* idle deployment with no active run → produces ONE
  ``controller_intents(kind='scale_to_zero')`` row
* deployment with an active ``AutomationRun`` (joined via
  ``InvocationSubject``) → SKIPPED, no intent recorded
* not-yet-idle deployment → no intent recorded
* lease term mismatch → :class:`LeaseLost` raised, no intents recorded

Uses the same in-memory SQLite + Base.metadata pattern as
``tests/services/apps/test_runtime_reaper.py`` so the
``app_runtime_deployments`` CHECK matrix and FK chain are real.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import models, models_automations  # noqa: F401  -- ensure registry
from app.database import Base
from app.models import AppVersion, MarketplaceApp
from app.models_automations import (
    AppInstance,
    AppRuntimeDeployment,
    AutomationDefinition,
    AutomationEvent,
    AutomationRun,
    ControllerIntent,
    InvocationSubject,
)
from app.services.apps.idle_reaper import reap_idle_runtimes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers (reused from the legacy reaper tests)
# ---------------------------------------------------------------------------


async def _seed_user(db: AsyncSession, suffix: str) -> models.User:
    suffix = f"{suffix}-{uuid.uuid4().hex[:6]}"
    user = models.User(
        id=uuid.uuid4(),
        email=f"reaper-{suffix}@example.com",
        hashed_password="x",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        name=f"Reaper {suffix}",
        username=f"reaper-{suffix}",
        slug=f"reaper-{suffix}",
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_app_and_version(
    db: AsyncSession, *, creator_id: UUID, slug: str
) -> tuple[MarketplaceApp, AppVersion]:
    app = MarketplaceApp(
        id=uuid.uuid4(),
        slug=f"{slug}-{uuid.uuid4().hex[:6]}",
        name=f"App {slug}",
        creator_user_id=creator_id,
        state="draft",
        visibility="public",
    )
    db.add(app)
    await db.flush()
    av = AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={},
        manifest_hash="sha256:" + ("a" * 64),
        bundle_hash="sha256:" + ("b" * 64),
        feature_set_hash="fs:test",
        required_features=[],
        approval_state="stage1_approved",
    )
    db.add(av)
    await db.flush()
    return app, av


async def _seed_runtime_deployment(
    db: AsyncSession,
    *,
    app_id: UUID,
    app_version_id: UUID,
    namespace: str = "ns-test",
    deployment_name: str = "deploy-test",
    last_activity_at: datetime | None = None,
    idle_timeout_seconds: int = 600,
) -> AppRuntimeDeployment:
    row = AppRuntimeDeployment(
        id=uuid.uuid4(),
        app_id=app_id,
        app_version_id=app_version_id,
        tenancy_model="per_install",
        state_model="stateless",
        namespace=namespace,
        primary_container_id=deployment_name,
        min_replicas=0,
        max_replicas=1,
        desired_replicas=1,
        idle_timeout_seconds=idle_timeout_seconds,
        last_activity_at=last_activity_at,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_app_instance(
    db: AsyncSession,
    *,
    app_id: UUID,
    app_version_id: UUID,
    installer_user_id: UUID,
    runtime_deployment_id: UUID,
) -> AppInstance:
    inst = AppInstance(
        id=uuid.uuid4(),
        app_id=app_id,
        app_version_id=app_version_id,
        installer_user_id=installer_user_id,
        state="installed",
        consent_record={},
        wallet_mix={},
        runtime_deployment_id=runtime_deployment_id,
    )
    db.add(inst)
    await db.flush()
    return inst


async def _seed_active_run(
    db: AsyncSession,
    *,
    creator_id: UUID,
    app_instance_id: UUID,
) -> AutomationRun:
    definition = AutomationDefinition(
        id=uuid.uuid4(),
        owner_user_id=creator_id,
        name=f"def-{uuid.uuid4().hex[:6]}",
        contract={},
        is_active=True,
    )
    db.add(definition)
    await db.flush()

    event = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=definition.id,
        trigger_kind="manual",
        payload={},
    )
    db.add(event)
    await db.flush()

    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=definition.id,
        event_id=event.id,
        status="running",
        heartbeat_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()

    subject = InvocationSubject(
        id=uuid.uuid4(),
        automation_run_id=run.id,
        app_instance_id=app_instance_id,
        payer_policy="installer",
        credit_source="opensail_credits",
    )
    db.add(subject)
    await db.flush()
    return run


async def _seed_controller_lease(db: AsyncSession, *, term: int) -> None:
    """Insert the controller lease row at the given term."""
    await db.execute(
        text(
            "INSERT INTO controller_leases (name, holder, term, expires_at, acquired_at) "
            "VALUES (:name, :holder, :term, :expires, :acquired)"
        ),
        {
            "name": "controller",
            "holder": "test-holder",
            "term": term,
            "expires": datetime.now(UTC) + timedelta(seconds=60),
            "acquired": datetime.now(UTC),
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_deployment_produces_intent(db: AsyncSession) -> None:
    user = await _seed_user(db, "idle")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="idle")
    now = datetime.now(UTC)
    deployment = await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=1200),
        namespace="ns-idle",
        deployment_name="deploy-idle",
    )
    await _seed_app_instance(
        db,
        app_id=app.id,
        app_version_id=av.id,
        installer_user_id=user.id,
        runtime_deployment_id=deployment.id,
    )
    await _seed_controller_lease(db, term=3)
    await db.commit()

    result = await reap_idle_runtimes(db, our_term=3, now=now)

    assert result.examined == 1
    assert result.intents_recorded == 1
    assert result.skipped_active == 0
    assert result.intents_failed == 0

    # Verify the intent row.
    intents = list(
        (
            await db.execute(
                select(ControllerIntent).where(
                    ControllerIntent.kind == "scale_to_zero"
                )
            )
        ).scalars().all()
    )
    assert len(intents) == 1
    assert intents[0].lease_term == 3
    assert intents[0].status == "pending"
    assert intents[0].target_ref["namespace"] == "ns-idle"
    assert intents[0].target_ref["deployment"] == "deploy-idle"
    assert intents[0].target_ref["runtime_deployment_id"] == str(deployment.id)


@pytest.mark.asyncio
async def test_active_run_blocks_intent(db: AsyncSession) -> None:
    user = await _seed_user(db, "active")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="active")
    now = datetime.now(UTC)
    deployment = await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=1200),
    )
    instance = await _seed_app_instance(
        db,
        app_id=app.id,
        app_version_id=av.id,
        installer_user_id=user.id,
        runtime_deployment_id=deployment.id,
    )
    await _seed_active_run(db, creator_id=user.id, app_instance_id=instance.id)
    await _seed_controller_lease(db, term=1)
    await db.commit()

    result = await reap_idle_runtimes(db, our_term=1, now=now)

    assert result.examined == 1
    assert result.skipped_active == 1
    assert result.intents_recorded == 0

    intents = list(
        (await db.execute(select(ControllerIntent))).scalars().all()
    )
    assert intents == []


@pytest.mark.asyncio
async def test_not_yet_idle_skipped(db: AsyncSession) -> None:
    user = await _seed_user(db, "fresh")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="fresh")
    now = datetime.now(UTC)
    await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=10),  # well within timeout
        idle_timeout_seconds=600,
    )
    await _seed_controller_lease(db, term=1)
    await db.commit()

    result = await reap_idle_runtimes(db, our_term=1, now=now)

    assert result.examined == 1
    assert result.intents_recorded == 0
    assert result.not_idle == 1


@pytest.mark.asyncio
async def test_lease_lost_raises_and_records_no_intents(db: AsyncSession) -> None:
    from app.services.automations.intents import LeaseLost

    user = await _seed_user(db, "leaselost")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="leaselost")
    now = datetime.now(UTC)
    await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=1200),
    )
    # Lease is at term=5 but reaper claims our_term=99.
    await _seed_controller_lease(db, term=5)
    await db.commit()

    with pytest.raises(LeaseLost):
        await reap_idle_runtimes(db, our_term=99, now=now)

    # No intents written under a stale term.
    intents = list(
        (await db.execute(select(ControllerIntent))).scalars().all()
    )
    assert intents == []
