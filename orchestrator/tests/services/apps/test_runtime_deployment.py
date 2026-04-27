"""Tests for the AppRuntimeDeployment primitive (Phase 3).

Covers:
  * ``per_install`` install creates a fresh AppRuntimeDeployment row with
    ``tenancy_model='per_install'`` and ``max_replicas=1``.
  * ``shared_singleton`` install creates ONE AppRuntimeDeployment + ONE
    K8s project across N installs — subsequent installs reuse the row
    and skip the Hub call entirely.
  * ``per_invocation`` install creates a runtime row pinned to
    ``min_replicas=0, max_replicas=0`` with no project + no volume.
  * DB CHECK constraints reject ``per_install_volume + max_replicas=2``
    and ``service_pvc + max_replicas=3``.
  * Manifest-level validation rejects ``per_install_volume +
    shared_singleton`` (a per-install volume requires a per-install
    runtime) before any side effects.

The fixtures spin up an in-memory SQLite database with the full schema —
the same pattern as ``tests/services/apps/test_projection.py``. A
``FakeHubClient`` stands in for the real volume-hub client.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing models_automations is what registers AppRuntimeDeployment +
# the Phase 1 projection tables on Base.metadata. Without this import the
# CREATE TABLE for app_runtime_deployments is not emitted by create_all
# and the tests fall over on first insert.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.services.apps import installer
from app.services.apps.installer import (
    AppRuntimeDeployment,
    ManifestInvalid,
    install_app,
)


# ---------------------------------------------------------------------------
# Fixtures — fresh in-memory SQLite per test.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite session with the full app schema installed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        # SQLite needs PRAGMA foreign_keys=ON so the CASCADE FKs and CHECK
        # constraints actually fire in tests.
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Fake hub client — counts how many volumes were minted across N installs.
# ---------------------------------------------------------------------------


class FakeHubClient:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []

    async def create_volume_from_bundle(
        self,
        *,
        bundle_hash: str,
        hint_node: str | None = None,
        timeout: float = 600.0,
    ) -> tuple[str, str]:
        self.create_calls.append({"bundle_hash": bundle_hash})
        # Each call mints a unique volume id so duplicate calls would
        # surface as DB conflicts (the partial UNIQUE on
        # app_instances(project_id) does not cover this directly, but a
        # second project create will pass — failing only if the test
        # explicitly inspects the call count).
        return f"vol-{uuid.uuid4().hex[:8]}", "node-test"


# ---------------------------------------------------------------------------
# Bundle config.json stub — install-time container materialization now reads
# ``.tesslate/config.json`` from the materialized volume via the orchestrator.
# These tests focus on the AppRuntimeDeployment primitive, not on container
# layout, so we stub the orchestrator with a minimal valid config and stay
# off the real Docker/K8s factory path.
# ---------------------------------------------------------------------------


import json as _json  # noqa: E402

_DEFAULT_BUNDLE_CONFIG_JSON = _json.dumps(
    {
        "primaryApp": "primary",
        "apps": {
            "primary": {
                "directory": "/app",
                "start": "node index.js",
                "port": 3000,
            }
        },
        "infrastructure": {},
        "connections": [],
    }
)


class _StubOrchestrator:
    async def read_file(self, **kwargs: Any) -> str | None:
        if kwargs.get("file_path") == ".tesslate/config.json":
            return _DEFAULT_BUNDLE_CONFIG_JSON
        return None


@pytest.fixture(autouse=True)
def _patch_install_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the install-time container materializer onto a stub orchestrator
    so the tests don't trip over the real DockerOrchestrator's ``/projects``
    mkdir on macOS dev machines.
    """
    import app.services.orchestration as _orchestration

    monkeypatch.setattr(
        _orchestration, "get_orchestrator", lambda *a, **kw: _StubOrchestrator()
    )


# ---------------------------------------------------------------------------
# Manifest builders — minimal 2026-05 manifests, parameterized by tenancy +
# state model so each test can pick its own runtime contract.
# ---------------------------------------------------------------------------


def _runtime_manifest(
    *,
    slug: str,
    tenancy_model: str,
    state_model: str,
    max_replicas: int = 1,
    min_replicas: int = 0,
) -> dict[str, Any]:
    return {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": f"com.example.{slug}",
            "name": f"App {slug}",
            "slug": slug,
            "version": "1.0.0",
        },
        "runtime": {
            "tenancy_model": tenancy_model,
            "state_model": state_model,
            "scaling": {
                "min_replicas": min_replicas,
                "max_replicas": max_replicas,
            },
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {"model": "free", "rate_percent": 0, "price_usd": 0},
        },
    }


# ---------------------------------------------------------------------------
# DB seed helpers.
# ---------------------------------------------------------------------------


async def _seed_user(db: AsyncSession, email_suffix: str) -> models.User:
    suffix = f"{email_suffix}-{uuid.uuid4().hex[:6]}"
    user = models.User(
        id=uuid.uuid4(),
        email=f"installer-{suffix}@example.com",
        hashed_password="x",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        name=f"Installer {suffix}",
        username=f"installer-{suffix}",
        slug=f"installer-{suffix}",
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_personal_team(db: AsyncSession, owner: models.User) -> models.Team:
    team = models.Team(
        id=uuid.uuid4(),
        name=f"{owner.email}'s team",
        slug=f"team-{uuid.uuid4().hex[:8]}",
        is_personal=True,
        created_by_id=owner.id,
    )
    db.add(team)
    await db.flush()
    return team


async def _seed_app_with_version(
    db: AsyncSession,
    *,
    creator_user_id: UUID,
    manifest: dict[str, Any],
    approval_state: str = "stage1_approved",
) -> tuple[models.MarketplaceApp, models.AppVersion]:
    app = models.MarketplaceApp(
        id=uuid.uuid4(),
        slug=manifest["app"]["slug"],
        name=manifest["app"]["name"],
        creator_user_id=creator_user_id,
        state="draft",
        visibility="public",
    )
    db.add(app)
    await db.flush()
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version=manifest["app"]["version"],
        manifest_schema_version=manifest["manifest_schema_version"],
        manifest_json=manifest,
        manifest_hash="sha256:" + ("a" * 64),
        bundle_hash="sha256:" + ("b" * 64),
        feature_set_hash="fs:test",
        required_features=[],
        approval_state=approval_state,
    )
    db.add(av)
    await db.flush()
    return app, av


def _consent() -> dict[str, Any]:
    return {
        "ai_compute": {"payer": "installer"},
        "general_compute": {"payer": "installer"},
        "platform_fee": {"model": "free"},
    }


# ---------------------------------------------------------------------------
# Tests — installer branching by tenancy_model.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_install_creates_fresh_runtime_deployment(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legacy default — one AppRuntimeDeployment per AppInstance.

    The CHECK matrix forces ``max_replicas=1`` for ``per_install_volume``
    so the runtime row inherits that ceiling regardless of what the
    manifest scaling block requests.
    """
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user = await _seed_user(db, "per-install")
    team = await _seed_personal_team(db, user)
    manifest = _runtime_manifest(
        slug="per-install-app",
        tenancy_model="per_install",
        state_model="per_install_volume",
        max_replicas=1,
    )
    _, av = await _seed_app_with_version(db, creator_user_id=user.id, manifest=manifest)
    hub = FakeHubClient()

    result = await install_app(
        db,
        installer_user_id=user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team.id,
    )

    # Exactly one Hub volume minted per install.
    assert len(hub.create_calls) == 1

    instance = await db.get(models_automations.AppInstance, result.app_instance_id)
    assert instance is not None
    assert instance.runtime_deployment_id is not None

    deployment = await db.get(AppRuntimeDeployment, instance.runtime_deployment_id)
    assert deployment is not None
    assert deployment.tenancy_model == "per_install"
    assert deployment.state_model == "per_install_volume"
    assert deployment.max_replicas == 1
    assert deployment.runtime_project_id == result.project_id
    assert deployment.volume_id == result.volume_id


@pytest.mark.asyncio
async def test_shared_singleton_reuses_existing_deployment(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple installs of a shared_singleton app converge on ONE
    AppRuntimeDeployment row + ONE K8s project. The Hub volume is minted
    exactly once across N installs.
    """
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")

    user_a = await _seed_user(db, "alice")
    user_b = await _seed_user(db, "bob")
    user_c = await _seed_user(db, "carol")
    team_a = await _seed_personal_team(db, user_a)
    team_b = await _seed_personal_team(db, user_b)
    team_c = await _seed_personal_team(db, user_c)

    manifest = _runtime_manifest(
        slug="shared-app",
        tenancy_model="shared_singleton",
        state_model="stateless",
        max_replicas=5,
    )
    _, av = await _seed_app_with_version(db, creator_user_id=user_a.id, manifest=manifest)
    hub = FakeHubClient()

    result_a = await install_app(
        db,
        installer_user_id=user_a.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team_a.id,
    )
    result_b = await install_app(
        db,
        installer_user_id=user_b.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team_b.id,
    )
    result_c = await install_app(
        db,
        installer_user_id=user_c.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team_c.id,
    )

    # Hub minted EXACTLY one volume across three installs — that's the
    # load-bearing assertion of shared_singleton tenancy.
    assert len(hub.create_calls) == 1

    # All three AppInstance rows point at the same runtime deployment.
    inst_a = await db.get(models_automations.AppInstance, result_a.app_instance_id)
    inst_b = await db.get(models_automations.AppInstance, result_b.app_instance_id)
    inst_c = await db.get(models_automations.AppInstance, result_c.app_instance_id)
    assert inst_a is not None and inst_b is not None and inst_c is not None
    assert (
        inst_a.runtime_deployment_id
        == inst_b.runtime_deployment_id
        == inst_c.runtime_deployment_id
    )
    # All three resolve to the same K8s project (the shared one).
    assert (
        inst_a.project_id
        == inst_b.project_id
        == inst_c.project_id
        == result_a.project_id
    )

    # And exactly one row in app_runtime_deployments for this app+version.
    rows = (
        await db.execute(
            select(AppRuntimeDeployment).where(
                AppRuntimeDeployment.app_id == av.app_id,
                AppRuntimeDeployment.app_version_id == av.id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenancy_model == "shared_singleton"
    assert rows[0].max_replicas == 5  # honored from manifest


@pytest.mark.asyncio
async def test_per_invocation_creates_runtime_with_zero_replicas(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """per_invocation installs have no persistent pods. The runtime row
    exists for accounting/dispatcher routing, but ``min_replicas`` and
    ``max_replicas`` are pinned to zero. No Hub volume is minted; no
    project is materialized.
    """
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user = await _seed_user(db, "per-inv")
    team = await _seed_personal_team(db, user)
    manifest = _runtime_manifest(
        slug="per-inv-app",
        tenancy_model="per_invocation",
        state_model="stateless",
    )
    _, av = await _seed_app_with_version(db, creator_user_id=user.id, manifest=manifest)
    hub = FakeHubClient()

    result = await install_app(
        db,
        installer_user_id=user.id,
        app_version_id=av.id,
        hub_client=hub,
        wallet_mix_consent=_consent(),
        mcp_consents=[],
        team_id=team.id,
    )

    # No Hub call, no project, no volume.
    assert hub.create_calls == []
    assert result.project_id is None
    assert result.volume_id is None
    assert result.node_name is None

    instance = await db.get(models_automations.AppInstance, result.app_instance_id)
    assert instance is not None
    assert instance.project_id is None
    assert instance.volume_id is None
    assert instance.runtime_deployment_id is not None

    deployment = await db.get(AppRuntimeDeployment, instance.runtime_deployment_id)
    assert deployment is not None
    assert deployment.tenancy_model == "per_invocation"
    assert deployment.min_replicas == 0
    assert deployment.max_replicas == 0
    assert deployment.desired_replicas == 0
    assert deployment.runtime_project_id is None
    assert deployment.volume_id is None


# ---------------------------------------------------------------------------
# Tests — DB CHECK constraint matrix.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_per_install_volume_rejects_max_replicas_above_one(
    db: AsyncSession,
) -> None:
    """A per_install_volume deployment with max_replicas > 1 is rejected
    by the CHECK constraint regardless of how the row was constructed.

    This exercises the constraint directly — no installer involved — so
    a future code path that bypasses the validation helpers still gets
    rejected by the DB.
    """
    user = await _seed_user(db, "chk-piv")
    manifest = _runtime_manifest(
        slug="chk-piv",
        tenancy_model="per_install",
        state_model="per_install_volume",
        max_replicas=1,  # manifest is harmless; we're testing the DB
    )
    app, av = await _seed_app_with_version(db, creator_user_id=user.id, manifest=manifest)

    bad = AppRuntimeDeployment(
        app_id=app.id,
        app_version_id=av.id,
        tenancy_model="per_install",
        state_model="per_install_volume",
        min_replicas=1,
        max_replicas=2,  # CHECK violation
        desired_replicas=2,
    )
    db.add(bad)
    with pytest.raises(IntegrityError) as excinfo:
        await db.flush()
    assert "chk_ard_per_install_volume_max_one" in str(excinfo.value)
    await db.rollback()


@pytest.mark.asyncio
async def test_check_service_pvc_rejects_max_replicas_above_one(
    db: AsyncSession,
) -> None:
    """A service_pvc deployment with max_replicas > 1 is rejected by the
    CHECK constraint. Exercises the constraint directly.
    """
    user = await _seed_user(db, "chk-pvc")
    manifest = _runtime_manifest(
        slug="chk-pvc",
        tenancy_model="per_install",
        state_model="per_install_volume",
        max_replicas=1,
    )
    app, av = await _seed_app_with_version(db, creator_user_id=user.id, manifest=manifest)

    bad = AppRuntimeDeployment(
        app_id=app.id,
        app_version_id=av.id,
        tenancy_model="per_install",
        state_model="service_pvc",
        min_replicas=1,
        max_replicas=3,  # CHECK violation
        desired_replicas=3,
    )
    db.add(bad)
    with pytest.raises(IntegrityError) as excinfo:
        await db.flush()
    assert "chk_ard_service_pvc_max_one" in str(excinfo.value)
    await db.rollback()


# ---------------------------------------------------------------------------
# Tests — manifest-level validation (defense in depth, fires before the DB).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_installer_rejects_per_install_volume_with_shared_singleton(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-install volume on a shared-singleton runtime is nonsensical
    — there's no per-install pod to mount it on. The installer raises
    ManifestInvalid BEFORE any side effects (no Hub call, no project
    create, no AppRuntimeDeployment row).
    """
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user = await _seed_user(db, "bad-combo")
    team = await _seed_personal_team(db, user)
    manifest = _runtime_manifest(
        slug="bad-combo",
        tenancy_model="shared_singleton",
        state_model="per_install_volume",
        max_replicas=1,
    )
    _, av = await _seed_app_with_version(db, creator_user_id=user.id, manifest=manifest)
    hub = FakeHubClient()

    with pytest.raises(ManifestInvalid) as excinfo:
        await install_app(
            db,
            installer_user_id=user.id,
            app_version_id=av.id,
            hub_client=hub,
            wallet_mix_consent=_consent(),
            mcp_consents=[],
            team_id=team.id,
        )
    assert "per_install_volume" in str(excinfo.value)
    assert "shared_singleton" in str(excinfo.value)
    # No side effects — no Hub volume minted.
    assert hub.create_calls == []
    # No runtime deployment row written.
    rows = (
        await db.execute(
            select(AppRuntimeDeployment).where(
                AppRuntimeDeployment.app_version_id == av.id
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_installer_rejects_per_invocation_with_persistent_state(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """per_invocation has no persistent pods, so a non-stateless state_model
    is rejected at install time. Also covered by ``_validate_runtime_contract``.
    """
    monkeypatch.setenv("TSL_APPS_DEV_AUTO_APPROVE", "1")
    user = await _seed_user(db, "bad-piv-stateful")
    team = await _seed_personal_team(db, user)
    manifest = _runtime_manifest(
        slug="bad-piv-stateful",
        tenancy_model="per_invocation",
        state_model="shared_volume",
    )
    _, av = await _seed_app_with_version(db, creator_user_id=user.id, manifest=manifest)
    hub = FakeHubClient()

    with pytest.raises(ManifestInvalid) as excinfo:
        await install_app(
            db,
            installer_user_id=user.id,
            app_version_id=av.id,
            hub_client=hub,
            wallet_mix_consent=_consent(),
            mcp_consents=[],
            team_id=team.id,
        )
    assert "per_invocation" in str(excinfo.value)
    assert "stateless" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Pure unit test — _validate_runtime_contract rejects bad combinations
# without any DB.
# ---------------------------------------------------------------------------


def test_validate_runtime_contract_rejects_replica_inversion() -> None:
    """``max_replicas < min_replicas`` is rejected before the DB sees it."""
    contract = installer._RuntimeContract(
        tenancy_model="per_install",
        state_model="stateless",
        min_replicas=2,
        max_replicas=1,
        desired_replicas=1,
        idle_timeout_seconds=600,
        concurrency_target=10,
        scaling_config={},
    )
    with pytest.raises(ManifestInvalid) as excinfo:
        installer._validate_runtime_contract(contract)
    assert "max_replicas" in str(excinfo.value)
