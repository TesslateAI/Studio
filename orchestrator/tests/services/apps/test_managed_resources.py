"""Tests for the managed-resource provisioners.

Covers all three public entry points (``add_postgres``, ``add_object_storage``,
``add_kv``) across:

* the unconfigured-and-stub-disabled path → ``ManagedResourcesNotConfigured``
* the ALLOW_STUB path → sentinel-DNS values returned + manifest patched
* the real-provisioner path → asyncpg / boto3 / redis monkey-patched to
  record the calls; assert the right SQL / API calls are issued.

All tests share an in-memory aiosqlite engine + a tmp-path-rooted project
workspace so the manifest patcher and migration helper writers have real
files to touch. The K8s ``CoreV1Api`` is a ``MagicMock`` so we can verify
Secret writes without a cluster.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.config import get_settings
from app.database import Base
from app.models import Project, Team, User
from app.services.apps.managed_resources import (
    ManagedResourcesNotConfigured,
    add_kv,
    add_object_storage,
    add_postgres,
    managed_db_secret_name,
    managed_kv_secret_name,
    managed_object_storage_secret_name,
)


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
    maker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_project(db: AsyncSession, tmp_path: Path):
    """Seed (User, Team, Project) and root the project workspace at tmp_path.

    Yields ``(project, project_root)``. Both ``managed_resources.get_project_path``
    and the workspace manifest scanner see the same on-disk root.
    """
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"u-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=False,
        name="Test User",
        username=f"user-{user_id.hex[:10]}",
        slug=f"user-{user_id.hex[:10]}",
    )
    db.add(user)

    team_id = uuid.uuid4()
    team = Team(
        id=team_id,
        slug=f"team-{team_id.hex[:10]}",
        name="Test Team",
        is_personal=True,
        created_by_id=user_id,
    )
    db.add(team)
    await db.flush()

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name="Sample App",
        slug=f"sample-app-{project_id.hex[:8]}",
        owner_id=user_id,
        team_id=team_id,
        visibility="team",
    )
    db.add(project)
    await db.flush()

    project_root = tmp_path / "project_root"
    project_root.mkdir()

    with patch(
        "app.services.apps.managed_resources.get_project_path",
        return_value=str(project_root),
    ):
        yield project, project_root


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """The settings object is ``lru_cache``-d; bust between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def core_v1():
    mock = MagicMock()
    mock.create_namespaced_secret = MagicMock(return_value=None)
    mock.patch_namespaced_secret = MagicMock(return_value=None)
    return mock


def _seed_manifest_yaml(project_root: Path) -> Path:
    """Pre-seed a minimal opensail.app.yaml so the patcher writes through."""
    manifest_yaml = (
        "manifest_schema_version: '2026-05'\n"
        "app:\n  id: com.test.app\n  name: Test App\n  version: 1.0.0\n"
        "runtime:\n"
        "  tenancy_model: per_install\n"
        "  state_model: per_install_volume\n"
        "  scaling:\n    max_replicas: 1\n"
        "billing:\n"
        "  ai_compute:\n    payer_default: installer\n"
        "  general_compute:\n    payer_default: installer\n"
        "  platform_fee:\n    rate_percent: 0\n    model: free\n"
    )
    path = project_root / "opensail.app.yaml"
    path.write_text(manifest_yaml)
    return path


# ---------------------------------------------------------------------------
# Unconfigured paths — every provisioner raises without env or ALLOW_STUB.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_postgres_raises_when_unconfigured(
    db, seeded_project, monkeypatch, core_v1
):
    monkeypatch.delenv("MANAGED_POSTGRES_ADMIN_URL", raising=False)
    monkeypatch.delenv("MANAGED_POSTGRES_ALLOW_STUB", raising=False)
    project, _root = seeded_project
    user = await db.get(User, project.owner_id)
    assert user is not None

    with pytest.raises(ManagedResourcesNotConfigured) as exc_info:
        await add_postgres(db, project=project, user=user, core_v1=core_v1)
    assert "MANAGED_POSTGRES_ADMIN_URL" in str(exc_info.value)
    # No Secret should have been written.
    core_v1.create_namespaced_secret.assert_not_called()


@pytest.mark.asyncio
async def test_add_object_storage_raises_when_unconfigured(
    db, seeded_project, monkeypatch, core_v1
):
    for var in (
        "MANAGED_OBJECT_STORAGE_ENDPOINT",
        "MANAGED_OBJECT_STORAGE_REGION",
        "MANAGED_OBJECT_STORAGE_ADMIN_KEY_ID",
        "MANAGED_OBJECT_STORAGE_ADMIN_SECRET",
        "MANAGED_OBJECT_STORAGE_ALLOW_STUB",
    ):
        monkeypatch.delenv(var, raising=False)
    project, _root = seeded_project
    user = await db.get(User, project.owner_id)
    assert user is not None

    with pytest.raises(ManagedResourcesNotConfigured) as exc_info:
        await add_object_storage(db, project=project, user=user, core_v1=core_v1)
    assert "MANAGED_OBJECT_STORAGE" in str(exc_info.value)
    core_v1.create_namespaced_secret.assert_not_called()


@pytest.mark.asyncio
async def test_add_kv_raises_when_unconfigured(
    db, seeded_project, monkeypatch, core_v1
):
    monkeypatch.delenv("MANAGED_REDIS_URL", raising=False)
    monkeypatch.delenv("MANAGED_REDIS_ALLOW_STUB", raising=False)
    project, _root = seeded_project
    user = await db.get(User, project.owner_id)
    assert user is not None

    with pytest.raises(ManagedResourcesNotConfigured) as exc_info:
        await add_kv(db, project=project, user=user, core_v1=core_v1)
    assert "MANAGED_REDIS_URL" in str(exc_info.value)
    core_v1.create_namespaced_secret.assert_not_called()


# ---------------------------------------------------------------------------
# ALLOW_STUB paths — sentinel-DNS values returned, manifest patched.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_postgres_allow_stub_returns_sentinel(
    db, seeded_project, monkeypatch, core_v1
):
    monkeypatch.delenv("MANAGED_POSTGRES_ADMIN_URL", raising=False)
    monkeypatch.setenv("MANAGED_POSTGRES_ALLOW_STUB", "1")
    project, project_root = seeded_project
    manifest_path = _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    result = await add_postgres(db, project=project, user=user, core_v1=core_v1)

    assert result.is_stub_provisioner is True
    assert "managed-postgres-pool" in result.connection_url
    assert result.secret_name == managed_db_secret_name(project.id)
    # Manifest patch flips state model + adds DATABASE_URL.
    assert result.manifest_patch["runtime"]["state_model"] == "external"
    assert (
        result.manifest_patch["compute"]["containers"][0]["env"]["DATABASE_URL"]
        == f"${{secret:{result.secret_name}/url}}"
    )
    # Disk patch resolved.
    assert result.manifest_path == str(manifest_path)
    # Secret written exactly once with stub annotation.
    core_v1.create_namespaced_secret.assert_called_once()
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert body.metadata.annotations["tesslate.io/provisioner-status"] == "stubbed"


@pytest.mark.asyncio
async def test_add_object_storage_allow_stub_returns_sentinel(
    db, seeded_project, monkeypatch, core_v1
):
    for var in (
        "MANAGED_OBJECT_STORAGE_ENDPOINT",
        "MANAGED_OBJECT_STORAGE_REGION",
        "MANAGED_OBJECT_STORAGE_ADMIN_KEY_ID",
        "MANAGED_OBJECT_STORAGE_ADMIN_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MANAGED_OBJECT_STORAGE_ALLOW_STUB", "1")
    project, project_root = seeded_project
    manifest_path = _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    result = await add_object_storage(
        db, project=project, user=user, core_v1=core_v1
    )

    assert result.is_stub_provisioner is True
    assert result.bucket.startswith("opensail-app-")
    assert "invalid" in result.endpoint  # sentinel host
    assert result.secret_name == managed_object_storage_secret_name(project.id)
    # Manifest patch wires all five S3_* env vars.
    env = result.manifest_patch["compute"]["containers"][0]["env"]
    assert set(env.keys()) == {
        "S3_ENDPOINT",
        "S3_REGION",
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    }
    assert env["S3_BUCKET"] == f"${{secret:{result.secret_name}/bucket}}"
    assert result.manifest_patch["runtime"]["state_model"] == "external"
    assert result.manifest_path == str(manifest_path)
    core_v1.create_namespaced_secret.assert_called_once()
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert "bucket" in body.string_data
    assert body.string_data["bucket"] == result.bucket


@pytest.mark.asyncio
async def test_add_kv_allow_stub_returns_sentinel(
    db, seeded_project, monkeypatch, core_v1
):
    monkeypatch.delenv("MANAGED_REDIS_URL", raising=False)
    monkeypatch.setenv("MANAGED_REDIS_ALLOW_STUB", "1")
    project, project_root = seeded_project
    manifest_path = _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    result = await add_kv(db, project=project, user=user, core_v1=core_v1)

    assert result.is_stub_provisioner is True
    assert "invalid" in result.redis_url
    assert result.prefix.startswith("app:")
    assert result.prefix.endswith(":")
    assert result.secret_name == managed_kv_secret_name(project.id)
    env = result.manifest_patch["compute"]["containers"][0]["env"]
    assert env["REDIS_URL"] == f"${{secret:{result.secret_name}/url}}"
    assert env["REDIS_PREFIX"] == f"${{secret:{result.secret_name}/prefix}}"
    assert result.manifest_patch["runtime"]["state_model"] == "external"
    assert result.manifest_path == str(manifest_path)
    core_v1.create_namespaced_secret.assert_called_once()


# ---------------------------------------------------------------------------
# Real-provisioner paths — monkeypatch external libs to record calls.
# ---------------------------------------------------------------------------


class _FakeAsyncpgConn:
    """Records every SQL string executed."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_add_postgres_real_provisioner_issues_ddl(
    db, seeded_project, monkeypatch, core_v1
):
    """Real path: connect to admin DSN, CREATE USER + CREATE DATABASE + GRANT."""
    monkeypatch.setenv(
        "MANAGED_POSTGRES_ADMIN_URL",
        "postgresql://admin:secret@pg-pool.example.com:5433/postgres",
    )
    monkeypatch.delenv("MANAGED_POSTGRES_ALLOW_STUB", raising=False)
    project, project_root = seeded_project
    _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    fake_conn = _FakeAsyncpgConn()

    async def _fake_connect(**_kwargs: Any) -> _FakeAsyncpgConn:
        return fake_conn

    # Patch the asyncpg.connect entry point. Our managed_resources module
    # imports asyncpg lazily inside the provisioner so we patch the
    # canonical attribute on the asyncpg module.
    import asyncpg

    monkeypatch.setattr(asyncpg, "connect", _fake_connect)

    result = await add_postgres(db, project=project, user=user, core_v1=core_v1)

    # SQL trace assertions.
    sql_blobs = [sql for sql, _ in fake_conn.executed]
    assert any(s.startswith("CREATE USER ") for s in sql_blobs), sql_blobs
    assert any(s.startswith("CREATE DATABASE ") for s in sql_blobs), sql_blobs
    assert any(s.startswith("GRANT ALL PRIVILEGES ") for s in sql_blobs), sql_blobs
    # The username is the generated db_name and shows up in CREATE DATABASE
    # OWNER.
    assert any(result.db_user in s for s in sql_blobs)
    # Connection was closed.
    assert fake_conn.closed is True

    # Real result, not a stub.
    assert result.is_stub_provisioner is False
    # URL points at the configured pool, NOT the sentinel host.
    assert "managed-postgres-pool" not in result.connection_url
    assert "pg-pool.example.com" in result.connection_url
    assert ":5433/" in result.connection_url

    # Secret marked real.
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert body.metadata.annotations["tesslate.io/provisioner-status"] == "real"


@pytest.mark.asyncio
async def test_add_object_storage_real_provisioner_creates_bucket(
    db, seeded_project, monkeypatch, core_v1
):
    """Real path: boto3.client('s3').create_bucket gets called with the
    derived bucket name + region constraint."""
    monkeypatch.setenv("MANAGED_OBJECT_STORAGE_ENDPOINT", "https://s3.example.com")
    monkeypatch.setenv("MANAGED_OBJECT_STORAGE_REGION", "eu-west-2")
    monkeypatch.setenv("MANAGED_OBJECT_STORAGE_ADMIN_KEY_ID", "AKIAFAKEKEY")
    monkeypatch.setenv("MANAGED_OBJECT_STORAGE_ADMIN_SECRET", "fakesecret")
    monkeypatch.delenv("MANAGED_OBJECT_STORAGE_ALLOW_STUB", raising=False)

    project, project_root = seeded_project
    _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    create_calls: list[dict[str, Any]] = []
    client_kwargs: list[dict[str, Any]] = []

    class _FakeS3Client:
        def create_bucket(self, **kwargs: Any) -> dict[str, Any]:
            create_calls.append(kwargs)
            return {"Location": f"/{kwargs['Bucket']}"}

    def _fake_client(service: str, **kwargs: Any) -> _FakeS3Client:
        assert service == "s3"
        client_kwargs.append(kwargs)
        return _FakeS3Client()

    import boto3

    monkeypatch.setattr(boto3, "client", _fake_client)

    result = await add_object_storage(
        db, project=project, user=user, core_v1=core_v1
    )

    assert result.is_stub_provisioner is False
    assert result.endpoint == "https://s3.example.com"
    assert result.region == "eu-west-2"
    assert result.bucket.startswith("opensail-app-")
    # Bucket creation was attempted exactly once with the right region
    # constraint (anything other than us-east-1 must include LocationConstraint).
    assert len(create_calls) == 1
    assert create_calls[0]["Bucket"] == result.bucket
    assert create_calls[0]["CreateBucketConfiguration"] == {
        "LocationConstraint": "eu-west-2"
    }
    # Boto session received the configured admin credentials.
    assert client_kwargs[0]["aws_access_key_id"] == "AKIAFAKEKEY"
    assert client_kwargs[0]["aws_secret_access_key"] == "fakesecret"
    assert client_kwargs[0]["endpoint_url"] == "https://s3.example.com"
    # Secret marked real, contains the bucket name.
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert body.metadata.annotations["tesslate.io/provisioner-status"] == "real"
    assert body.string_data["bucket"] == result.bucket


@pytest.mark.asyncio
async def test_add_kv_real_provisioner_runs_info(
    db, seeded_project, monkeypatch, core_v1
):
    """Real path: redis.asyncio.from_url(...).info() is called to verify
    reachability; the configured URL flows through to the result."""
    monkeypatch.setenv(
        "MANAGED_REDIS_URL", "redis://kv-pool.example.com:6380/0"
    )
    monkeypatch.delenv("MANAGED_REDIS_ALLOW_STUB", raising=False)
    project, project_root = seeded_project
    _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    info_calls: list[None] = []
    close_calls: list[str] = []
    from_url_calls: list[tuple[str, dict[str, Any]]] = []

    class _FakeRedis:
        async def info(self) -> dict[str, str]:
            info_calls.append(None)
            return {"redis_version": "7.2.0"}

        async def aclose(self) -> None:
            close_calls.append("aclose")

    def _fake_from_url(url: str, **kwargs: Any) -> _FakeRedis:
        from_url_calls.append((url, kwargs))
        return _FakeRedis()

    import redis.asyncio as redis_async

    monkeypatch.setattr(redis_async, "from_url", _fake_from_url)

    result = await add_kv(db, project=project, user=user, core_v1=core_v1)

    assert result.is_stub_provisioner is False
    assert result.redis_url == "redis://kv-pool.example.com:6380/0"
    assert result.prefix.startswith("app:")
    # Verified reachability + closed cleanly.
    assert len(info_calls) == 1
    assert "aclose" in close_calls
    # from_url received the configured URL + a connect timeout.
    assert from_url_calls[0][0] == "redis://kv-pool.example.com:6380/0"
    assert "socket_connect_timeout" in from_url_calls[0][1]
    # Secret marked real with both keys.
    body = core_v1.create_namespaced_secret.call_args.kwargs["body"]
    assert body.metadata.annotations["tesslate.io/provisioner-status"] == "real"
    assert body.string_data["url"] == result.redis_url
    assert body.string_data["prefix"] == result.prefix


# ---------------------------------------------------------------------------
# Manifest patch shape sanity (one assertion per provisioner that the
# state_model flip + env-var wiring lands in the patch).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_provisioners_patch_state_model_external(
    db, seeded_project, monkeypatch, core_v1
):
    """Every provisioner flips runtime.state_model='external'."""
    monkeypatch.setenv("MANAGED_POSTGRES_ALLOW_STUB", "1")
    monkeypatch.setenv("MANAGED_OBJECT_STORAGE_ALLOW_STUB", "1")
    monkeypatch.setenv("MANAGED_REDIS_ALLOW_STUB", "1")
    project, project_root = seeded_project
    _seed_manifest_yaml(project_root)
    user = await db.get(User, project.owner_id)
    assert user is not None

    pg = await add_postgres(db, project=project, user=user, core_v1=core_v1)
    obj = await add_object_storage(db, project=project, user=user, core_v1=core_v1)
    kv = await add_kv(db, project=project, user=user, core_v1=core_v1)

    for r in (pg, obj, kv):
        assert r.manifest_patch["runtime"]["state_model"] == "external"
        # max_replicas bumped past 1 — that's the whole point of the upgrade.
        assert r.manifest_patch["runtime"]["scaling"]["max_replicas"] > 1

    # And each has its own characteristic env var slot.
    pg_env = pg.manifest_patch["compute"]["containers"][0]["env"]
    obj_env = obj.manifest_patch["compute"]["containers"][0]["env"]
    kv_env = kv.manifest_patch["compute"]["containers"][0]["env"]
    assert "DATABASE_URL" in pg_env
    assert "S3_BUCKET" in obj_env
    assert "REDIS_URL" in kv_env
