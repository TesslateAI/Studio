"""Tests for the AppRuntimeDeployment idle reaper (Phase 4).

Covers the four cases called out in the plan:

1. A deployment past its idle timeout with no active runs is scaled to
   zero, ``scaled_to_zero_at`` is stamped, and ``desired_replicas`` is
   reset.
2. A deployment with an active (non-terminal) ``AutomationRun`` joined
   through :class:`InvocationSubject` is left alone — no K8s call fires.
3. A shared-singleton runtime backing N installs is reaped exactly once
   per pass (one K8s scale call total, not N).
4. ``deployment_mode='docker'`` is a no-op — the reaper returns clean
   counters and never touches K8s.

The tests use the same in-memory SQLite + Base.metadata pattern as
``tests/services/apps/test_runtime_deployment.py`` so the
``app_runtime_deployments`` CHECK matrix and the
``app_instances.runtime_deployment_id`` FK are real.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing models_automations is what registers AppRuntimeDeployment +
# the Phase 1/2 automation tables on Base.metadata. Without this import
# the CREATE TABLE for app_runtime_deployments + automation_runs +
# invocation_subjects is not emitted by create_all and the tests fall
# over on first insert.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models import AppVersion, MarketplaceApp
from app.models_automations import (
    AppInstance,
    AppRuntimeDeployment,
    AutomationDefinition,
    AutomationEvent,
    AutomationRun,
    InvocationSubject,
)
from app.services.apps.runtime_reaper import ReapResult, reap_idle_runtimes


# ---------------------------------------------------------------------------
# Fake K8s client — records every call so tests can assert exactly what
# the reaper drove on the cluster.
# ---------------------------------------------------------------------------


class _FakeAppsV1:
    def __init__(self, parent: "FakeK8sClient") -> None:
        self._parent = parent

    def patch_namespaced_deployment_scale(
        self, *, name: str, namespace: str, body: dict[str, Any]
    ) -> None:
        self._parent.scale_calls.append(
            {"name": name, "namespace": namespace, "body": body}
        )


class _FakeCoreV1:
    def __init__(self, parent: "FakeK8sClient") -> None:
        self._parent = parent

    def list_namespaced_pod(self, *, namespace: str, label_selector: str) -> Any:
        self._parent.list_pod_calls.append(
            {"namespace": namespace, "label_selector": label_selector}
        )

        class _PodList:
            items: list[Any] = []

        return _PodList()

    def delete_namespaced_pod(
        self, *, name: str, namespace: str, grace_period_seconds: int
    ) -> None:
        self._parent.delete_pod_calls.append(
            {
                "name": name,
                "namespace": namespace,
                "grace_period_seconds": grace_period_seconds,
            }
        )


class FakeK8sClient:
    def __init__(self) -> None:
        self.scale_calls: list[dict[str, Any]] = []
        self.list_pod_calls: list[dict[str, Any]] = []
        self.delete_pod_calls: list[dict[str, Any]] = []
        self.apps_v1 = _FakeAppsV1(self)
        self.core_v1 = _FakeCoreV1(self)


# ---------------------------------------------------------------------------
# DB fixture — fresh SQLite per test.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        # CHECK constraints + CASCADE FKs need the SQLite pragma.
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers — minimal rows; the reaper only touches the columns it needs.
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
    tenancy_model: str = "per_install",
    state_model: str = "stateless",
    namespace: str | None = "ns-test",
    deployment_name: str | None = "deploy-test",
    last_activity_at: datetime | None = None,
    idle_timeout_seconds: int = 600,
    desired_replicas: int = 1,
    max_replicas: int = 1,
    min_replicas: int = 0,
) -> AppRuntimeDeployment:
    row = AppRuntimeDeployment(
        id=uuid.uuid4(),
        app_id=app_id,
        app_version_id=app_version_id,
        tenancy_model=tenancy_model,
        state_model=state_model,
        namespace=namespace,
        primary_container_id=deployment_name,
        min_replicas=min_replicas,
        max_replicas=max_replicas,
        desired_replicas=desired_replicas,
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
    runtime_deployment_id: UUID | None,
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


async def _seed_automation_run(
    db: AsyncSession,
    *,
    status: str,
    creator_id: UUID,
    app_instance_id: UUID,
) -> AutomationRun:
    """Seed an AutomationDefinition + AutomationEvent + AutomationRun
    + InvocationSubject linking the run to the given app_instance."""
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
        status=status,
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


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaps_idle_deployment_with_no_active_runs(db: AsyncSession) -> None:
    """An idle deployment past its timeout is scaled to zero exactly once
    and ``scaled_to_zero_at`` is stamped on the row.
    """
    user = await _seed_user(db, "idle")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="idle")
    now = datetime.now(UTC)
    deployment = await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=1200),  # well past 600s
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
    await db.commit()

    fake_k8s = FakeK8sClient()
    result = await reap_idle_runtimes(
        db,
        now=now,
        k8s_client=fake_k8s,
        deployment_mode="kubernetes",
    )

    assert isinstance(result, ReapResult)
    assert result.examined == 1
    assert result.skipped_active == 0
    assert result.reaped == 1
    assert result.timeout_killed == 0

    # K8s saw exactly one scale-to-zero call against the right target.
    assert len(fake_k8s.scale_calls) == 1
    call = fake_k8s.scale_calls[0]
    assert call["namespace"] == "ns-idle"
    assert call["name"] == "deploy-idle"
    assert call["body"] == {"spec": {"replicas": 0}}

    # No SIGKILL fallback fired (no active runs to outwait).
    assert fake_k8s.delete_pod_calls == []

    refreshed = await db.get(AppRuntimeDeployment, deployment.id)
    assert refreshed is not None
    assert refreshed.scaled_to_zero_at is not None
    assert refreshed.desired_replicas == 0


@pytest.mark.asyncio
async def test_skips_deployment_with_active_run(db: AsyncSession) -> None:
    """A non-terminal AutomationRun (joined via InvocationSubject ⟶
    AppInstance ⟶ AppRuntimeDeployment) blocks reaping. No K8s scale
    call is made.
    """
    user = await _seed_user(db, "active")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="active")
    now = datetime.now(UTC)
    deployment = await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=1200),
        namespace="ns-active",
        deployment_name="deploy-active",
    )
    instance = await _seed_app_instance(
        db,
        app_id=app.id,
        app_version_id=av.id,
        installer_user_id=user.id,
        runtime_deployment_id=deployment.id,
    )
    await _seed_automation_run(
        db,
        status="running",
        creator_id=user.id,
        app_instance_id=instance.id,
    )
    await db.commit()

    fake_k8s = FakeK8sClient()
    result = await reap_idle_runtimes(
        db,
        now=now,
        k8s_client=fake_k8s,
        deployment_mode="kubernetes",
    )

    assert result.examined == 1
    assert result.skipped_active == 1
    assert result.reaped == 0
    assert result.timeout_killed == 0
    assert fake_k8s.scale_calls == []

    refreshed = await db.get(AppRuntimeDeployment, deployment.id)
    assert refreshed is not None
    assert refreshed.scaled_to_zero_at is None
    assert refreshed.desired_replicas == 1


@pytest.mark.asyncio
async def test_shared_singleton_one_runtime_many_installs_reaps_once(
    db: AsyncSession,
) -> None:
    """A shared_singleton runtime backing 5 AppInstance rows, all idle,
    triggers exactly ONE K8s scale call — proving the reaper acts on
    the deployment row, not on the install rows.
    """
    user = await _seed_user(db, "shared")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="shared")
    now = datetime.now(UTC)
    deployment = await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        tenancy_model="shared_singleton",
        state_model="stateless",
        max_replicas=5,
        last_activity_at=now - timedelta(seconds=1200),
        namespace="ns-shared",
        deployment_name="deploy-shared",
    )
    for i in range(5):
        installer = await _seed_user(db, f"installer-{i}")
        await _seed_app_instance(
            db,
            app_id=app.id,
            app_version_id=av.id,
            installer_user_id=installer.id,
            runtime_deployment_id=deployment.id,
        )
    await db.commit()

    fake_k8s = FakeK8sClient()
    result = await reap_idle_runtimes(
        db,
        now=now,
        k8s_client=fake_k8s,
        deployment_mode="kubernetes",
    )

    assert result.examined == 1
    assert result.reaped == 1
    assert result.skipped_active == 0
    # The load-bearing assertion: ONE K8s scale call across 5 installs.
    assert len(fake_k8s.scale_calls) == 1


@pytest.mark.asyncio
async def test_docker_mode_is_no_op(db: AsyncSession) -> None:
    """Docker mode skips reaping entirely. The reaper returns clean
    counters (``examined`` reflects how many rows it inspected) and
    makes zero K8s calls — even when an idle deployment exists.
    """
    user = await _seed_user(db, "docker")
    app, av = await _seed_app_and_version(db, creator_id=user.id, slug="docker")
    now = datetime.now(UTC)
    await _seed_runtime_deployment(
        db,
        app_id=app.id,
        app_version_id=av.id,
        last_activity_at=now - timedelta(seconds=1200),
        namespace="ns-docker",
        deployment_name="deploy-docker",
    )
    await db.commit()

    fake_k8s = FakeK8sClient()
    result = await reap_idle_runtimes(
        db,
        now=now,
        k8s_client=fake_k8s,
        deployment_mode="docker",
    )

    assert result.examined == 1
    assert result.reaped == 0
    assert result.skipped_active == 0
    assert result.timeout_killed == 0
    assert fake_k8s.scale_calls == []
    assert fake_k8s.delete_pod_calls == []
