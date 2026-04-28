"""Tests for the per-user K8s Secret propagator (Phase 3, Wave 1B).

Covered:
  * propagate_user_secrets with one user_mcp_config grant → string_data
    has the right (prefixed) keys, K8s create called once.
  * 409 from create → patch is called instead.
  * oauth + env grant → skipped with a warning, not added to string_data.
  * No env grants for the install → returns {} and skips the K8s call.
  * Mix of upserted + skipped grants → only upserted creds land in
    string_data, status dict reports both outcomes.
  * delete_user_secrets happy path → returns True.
  * delete_user_secrets 404 → returns False.
  * Other ApiException on delete → propagates.

Strategy
--------
Every test mocks the ``CoreV1Api`` (no real K8s). Database setup mirrors
``test_connector_proxy.py``: in-memory SQLite + StaticPool so we can seed
real ``UserMcpConfig`` rows whose ``credentials`` column was Fernet-
encrypted by the production ``encrypt_credentials`` helper. That gives the
test the same decrypt path that ships in production — no test-only
shortcuts around the crypto layer.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from kubernetes.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models import McpOAuthConnection, User, UserMcpConfig
from app.models_automations import (
    AppConnectorGrant,
    AppConnectorRequirement,
    AppInstance,
)
from app.services.apps.user_secret_propagator import (
    delete_user_secrets,
    propagate_user_secrets,
    user_secret_name,
)
from app.services.channels.registry import encrypt_credentials


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


def _make_core_v1_mock() -> MagicMock:
    """Mock CoreV1Api with create / patch / delete stubs."""
    m = MagicMock()
    m.create_namespaced_secret = MagicMock(return_value=None)
    m.patch_namespaced_secret = MagicMock(return_value=None)
    m.delete_namespaced_secret = MagicMock(return_value=None)
    return m


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_install(
    db: AsyncSession,
    *,
    user: User | None = None,
) -> AppInstance:
    """Create a minimal AppInstance + parent rows. Caller adds grants."""
    if user is None:
        uid = uuid.uuid4()
        user = User(
            id=uid,
            email=f"u-{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            name="Test User",
            username=f"user-{uid.hex[:10]}",
            slug=f"user-{uid.hex[:10]}",
        )
        db.add(user)

    from app.models import AppVersion, MarketplaceApp

    mkt = MarketplaceApp(
        id=uuid.uuid4(),
        slug=f"app-{uuid.uuid4().hex[:8]}",
        name="Test App",
        creator_user_id=user.id,
    )
    db.add(mkt)
    av = AppVersion(
        id=uuid.uuid4(),
        app_id=mkt.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={},
        manifest_hash="hash-" + uuid.uuid4().hex[:16],
        feature_set_hash="fs-" + uuid.uuid4().hex[:16],
    )
    db.add(av)
    await db.flush()

    instance = AppInstance(
        id=uuid.uuid4(),
        app_id=mkt.id,
        app_version_id=av.id,
        installer_user_id=user.id,
        state="installed",
    )
    db.add(instance)
    await db.flush()
    return instance


async def _add_user_mcp_grant(
    db: AsyncSession,
    *,
    instance: AppInstance,
    connector_id: str,
    credentials: dict[str, str],
    exposure: str = "env",
) -> AppConnectorGrant:
    """Seed a UserMcpConfig + matching AppConnectorRequirement + grant."""
    user_id = instance.installer_user_id

    requirement = AppConnectorRequirement(
        id=uuid.uuid4(),
        app_version_id=instance.app_version_id,
        connector_id=connector_id,
        kind="api_key",
        scopes=[],
        exposure=exposure,
    )
    db.add(requirement)

    cfg = UserMcpConfig(
        id=uuid.uuid4(),
        user_id=user_id,
        scope_level="user",
        is_active=True,
        credentials=encrypt_credentials(credentials),
    )
    db.add(cfg)
    await db.flush()

    grant = AppConnectorGrant(
        id=uuid.uuid4(),
        app_instance_id=instance.id,
        requirement_id=requirement.id,
        resolved_ref={"kind": "user_mcp_config", "id": str(cfg.id)},
        exposure_at_grant=exposure,
        granted_by_user_id=user_id,
    )
    db.add(grant)
    await db.flush()
    return grant


async def _add_oauth_env_grant(
    db: AsyncSession,
    *,
    instance: AppInstance,
    connector_id: str,
) -> AppConnectorGrant:
    """Seed an oauth_connection grant with exposure_at_grant='env'.

    Wave 1B's Pydantic validator should reject this combination at install
    time. We seed it directly so the propagator's defensive skip-and-warn
    path can be exercised.
    """
    user_id = instance.installer_user_id

    requirement = AppConnectorRequirement(
        id=uuid.uuid4(),
        app_version_id=instance.app_version_id,
        connector_id=connector_id,
        kind="oauth",
        scopes=[],
        exposure="env",
    )
    db.add(requirement)

    cfg = UserMcpConfig(
        id=uuid.uuid4(),
        user_id=user_id,
        scope_level="user",
        is_active=True,
    )
    db.add(cfg)
    await db.flush()

    oauth = McpOAuthConnection(
        id=uuid.uuid4(),
        user_mcp_config_id=cfg.id,
        server_url="https://example.test",
        tokens_encrypted=encrypt_credentials({"access_token": "secret-token"}),
        client_info_encrypted=encrypt_credentials({"client_id": "test"}),
        registration_method="dcr",
    )
    db.add(oauth)
    await db.flush()

    grant = AppConnectorGrant(
        id=uuid.uuid4(),
        app_instance_id=instance.id,
        requirement_id=requirement.id,
        resolved_ref={"kind": "oauth_connection", "id": str(oauth.id)},
        exposure_at_grant="env",
        granted_by_user_id=user_id,
    )
    db.add(grant)
    await db.flush()
    return grant


# ---------------------------------------------------------------------------
# propagate_user_secrets — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propagate_creates_secret_with_prefixed_keys(db: AsyncSession) -> None:
    instance = await _seed_install(db)
    await _add_user_mcp_grant(
        db,
        instance=instance,
        connector_id="linear",
        credentials={"api_key": "lin_pat_abc123", "workspace": "tesslate"},
    )
    await db.commit()

    core_v1 = _make_core_v1_mock()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {"linear": "upserted"}
    core_v1.create_namespaced_secret.assert_called_once()
    core_v1.patch_namespaced_secret.assert_not_called()

    call_kwargs = core_v1.create_namespaced_secret.call_args.kwargs
    assert call_kwargs["namespace"] == "proj-test"
    body = call_kwargs["body"]
    assert body.metadata.name == user_secret_name(instance.id)
    assert body.metadata.namespace == "proj-test"
    assert body.metadata.labels["tesslate.io/managed-by"] == "user-secret-propagator"
    assert body.metadata.labels["tesslate.io/app-instance-id"] == str(instance.id)
    assert body.type == "Opaque"
    # Keys are prefixed by connector_id and sanitized.
    assert body.string_data == {
        "linear_api_key": "lin_pat_abc123",
        "linear_workspace": "tesslate",
    }


@pytest.mark.asyncio
async def test_propagate_409_falls_back_to_patch(db: AsyncSession) -> None:
    instance = await _seed_install(db)
    await _add_user_mcp_grant(
        db,
        instance=instance,
        connector_id="github",
        credentials={"token": "ghp_xyz"},
    )
    await db.commit()

    core_v1 = _make_core_v1_mock()
    core_v1.create_namespaced_secret.side_effect = ApiException(status=409, reason="exists")

    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {"github": "upserted"}
    core_v1.create_namespaced_secret.assert_called_once()
    core_v1.patch_namespaced_secret.assert_called_once()
    patch_kwargs = core_v1.patch_namespaced_secret.call_args.kwargs
    assert patch_kwargs["name"] == user_secret_name(instance.id)
    assert patch_kwargs["namespace"] == "proj-test"
    assert patch_kwargs["body"]["stringData"] == {"github_token": "ghp_xyz"}


@pytest.mark.asyncio
async def test_propagate_other_api_exception_propagates(db: AsyncSession) -> None:
    instance = await _seed_install(db)
    await _add_user_mcp_grant(
        db,
        instance=instance,
        connector_id="github",
        credentials={"token": "ghp_xyz"},
    )
    await db.commit()

    core_v1 = _make_core_v1_mock()
    core_v1.create_namespaced_secret.side_effect = ApiException(status=500, reason="boom")

    with pytest.raises(ApiException):
        await propagate_user_secrets(
            db,
            core_v1,
            app_instance=instance,
            target_namespace="proj-test",
        )


# ---------------------------------------------------------------------------
# propagate_user_secrets — defensive paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_env_grant_is_skipped_and_warned(db: AsyncSession) -> None:
    instance = await _seed_install(db)
    await _add_oauth_env_grant(db, instance=instance, connector_id="slack")
    await db.commit()

    core_v1 = _make_core_v1_mock()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {"slack": "skipped_oauth_env_invalid"}
    # We still upsert an (empty-ish) Secret so a pod's envFrom doesn't
    # explode with "Secret not found"; the slack token simply isn't in it.
    core_v1.create_namespaced_secret.assert_called_once()
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert body.string_data == {}


@pytest.mark.asyncio
async def test_no_env_grants_returns_empty_and_skips_k8s(db: AsyncSession) -> None:
    instance = await _seed_install(db)
    # No grants seeded.
    await db.commit()

    core_v1 = _make_core_v1_mock()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {}
    core_v1.create_namespaced_secret.assert_not_called()
    core_v1.patch_namespaced_secret.assert_not_called()


@pytest.mark.asyncio
async def test_revoked_grant_is_excluded(db: AsyncSession) -> None:
    from datetime import UTC, datetime

    instance = await _seed_install(db)
    grant = await _add_user_mcp_grant(
        db,
        instance=instance,
        connector_id="linear",
        credentials={"api_key": "lin_pat_abc123"},
    )
    grant.revoked_at = datetime.now(UTC)
    await db.commit()

    core_v1 = _make_core_v1_mock()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {}
    core_v1.create_namespaced_secret.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_exposure_grant_is_excluded(db: AsyncSession) -> None:
    """Sanity check: ``exposure='proxy'`` grants belong to the Connector
    Proxy, not this propagator. They must never land in the env Secret."""
    instance = await _seed_install(db)
    await _add_user_mcp_grant(
        db,
        instance=instance,
        connector_id="linear",
        credentials={"api_key": "lin_pat_abc123"},
        exposure="proxy",
    )
    await db.commit()

    core_v1 = _make_core_v1_mock()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {}
    core_v1.create_namespaced_secret.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_grants_partition_correctly(db: AsyncSession) -> None:
    instance = await _seed_install(db)
    await _add_user_mcp_grant(
        db,
        instance=instance,
        connector_id="linear",
        credentials={"api_key": "lin_pat_abc123"},
    )
    await _add_oauth_env_grant(db, instance=instance, connector_id="slack")
    await db.commit()

    core_v1 = _make_core_v1_mock()
    statuses = await propagate_user_secrets(
        db,
        core_v1,
        app_instance=instance,
        target_namespace="proj-test",
    )

    assert statuses == {
        "linear": "upserted",
        "slack": "skipped_oauth_env_invalid",
    }
    core_v1.create_namespaced_secret.assert_called_once()
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    # Only the linear creds land in the Secret; oauth+env was refused.
    assert body.string_data == {"linear_api_key": "lin_pat_abc123"}


# ---------------------------------------------------------------------------
# delete_user_secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_happy_path_returns_true() -> None:
    core_v1 = _make_core_v1_mock()
    instance_id = uuid.uuid4()

    deleted = await delete_user_secrets(
        core_v1,
        app_instance_id=instance_id,
        target_namespace="proj-test",
    )

    assert deleted is True
    core_v1.delete_namespaced_secret.assert_called_once_with(
        name=user_secret_name(instance_id),
        namespace="proj-test",
    )


@pytest.mark.asyncio
async def test_delete_404_returns_false() -> None:
    core_v1 = _make_core_v1_mock()
    core_v1.delete_namespaced_secret.side_effect = ApiException(status=404, reason="not found")

    deleted = await delete_user_secrets(
        core_v1,
        app_instance_id=uuid.uuid4(),
        target_namespace="proj-test",
    )

    assert deleted is False


@pytest.mark.asyncio
async def test_delete_other_api_error_propagates() -> None:
    core_v1 = _make_core_v1_mock()
    core_v1.delete_namespaced_secret.side_effect = ApiException(status=500, reason="boom")

    with pytest.raises(ApiException):
        await delete_user_secrets(
            core_v1,
            app_instance_id=uuid.uuid4(),
            target_namespace="proj-test",
        )
