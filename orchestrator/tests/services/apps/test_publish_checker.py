"""Tests for the per-replica safety publish-time checker + add_postgres upgrade.

Covers:
  * ``check_state_model`` with a project that ships a SQLite file →
    ``state_model='per_install_volume'``, ``max_replicas=1``, sqlite warning,
    add_postgres upgrade offer present.
  * ``check_state_model`` with a stateless project (no .db files, no
    Container.startup_command tells, manifest declares ``stateless``) →
    ``state_model='stateless'``, max_replicas honours the manifest, no
    upgrade offers.
  * ``check_state_model`` with a Container.startup_command containing
    ``next dev`` and a ``.next/cache`` directory present → framework_pattern
    warning fired with the right detected_at.
  * ``add_postgres`` returns the stubbed connection URL, writes the K8s
    Secret via the injected mock client, and patches the manifest
    in-place when ``opensail.app.yaml`` exists in the workspace.

Strategy
--------
In-memory SQLite + StaticPool so the schema is created cheaply and we
can seed real ``Project`` + ``Container`` rows. The K8s client is a
``MagicMock`` (no real cluster). The project workspace is rooted under a
``tmp_path`` so file scans actually touch real files instead of going
through a layer of mocks.

The User/Team/Project triple is seeded with the minimal columns
``Base.metadata.create_all`` needs — every test that needs a real
project shares the ``seeded_project`` fixture.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models import Container, Project, Team, User
from app.services.apps.app_manifest import AppManifest2026_05
from app.services.apps.managed_resources import (
    add_postgres,
    managed_db_secret_name,
)
from app.services.apps.publish_checker import (
    DEFAULT_SCALABLE_MAX_REPLICAS,
    STATE_MODEL_PER_INSTALL_VOLUME,
    STATE_MODEL_STATELESS,
    WARNING_FRAMEWORK_PATTERN,
    WARNING_SQLITE_DETECTED,
    check_state_model,
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
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


def _stub_manifest(
    *,
    state_model: str = "per_install_volume",
    max_replicas: int = 1,
    write_scope: list[str] | None = None,
) -> AppManifest2026_05:
    """Smallest valid 2026-05 manifest the checker accepts.

    The Pydantic mirror enforces the constraint matrix at construction
    time, so callers cannot pass ``state_model='per_install_volume'`` +
    ``max_replicas=2`` here — that's the right contract: the checker
    operates on already-validated manifests.
    """
    runtime: dict = {
        "tenancy_model": "per_install",
        "state_model": state_model,
        "scaling": {"max_replicas": max_replicas},
    }
    if write_scope is not None and state_model in (
        "per_install_volume",
        "service_pvc",
        "shared_volume",
    ):
        runtime["storage"] = {"write_scope": write_scope}
    raw = {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": "com.test.app",
            "name": "Test App",
            "version": "1.0.0",
        },
        "runtime": runtime,
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {"rate_percent": 0, "model": "free"},
        },
    }
    return AppManifest2026_05.model_validate(raw)


@pytest_asyncio.fixture
async def seeded_project(db: AsyncSession, tmp_path: Path):
    """Seed (User, Team, Project) and root the project workspace at tmp_path.

    Returns a tuple ``(project, project_root)`` where ``project_root`` is
    the absolute Path the publish_checker will scan. We patch
    ``get_project_path`` (used both by the checker and by
    ``managed_resources``) so the ``users/{uid}/{pid}`` path it composes
    actually exists.
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

    # Patch get_project_path so both publish_checker and managed_resources
    # see the same on-disk root.
    with patch(
        "app.services.apps.publish_checker.get_project_path",
        return_value=str(project_root),
    ), patch(
        "app.services.apps.managed_resources.get_project_path",
        return_value=str(project_root),
    ):
        yield project, project_root


async def _add_container(
    db: AsyncSession,
    project: Project,
    *,
    name: str = "web",
    startup_command: str | None = None,
) -> Container:
    container = Container(
        id=uuid.uuid4(),
        project_id=project.id,
        name=name,
        directory=name,
        container_name=f"{project.slug}-{name}",
        startup_command=startup_command,
    )
    db.add(container)
    await db.flush()
    return container


# ---------------------------------------------------------------------------
# check_state_model — sqlite-detected path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_state_model_sqlite_detected(db, seeded_project):
    """A project shipping a /app/data/sessions.db file → pin to 1, offer postgres."""
    project, project_root = seeded_project
    data_dir = project_root / "app" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "sessions.db").write_bytes(b"SQLite format 3\x00")

    manifest = _stub_manifest(
        state_model="per_install_volume",
        max_replicas=1,
        write_scope=["/app/data"],
    )

    verdict = await check_state_model(db, project=project, manifest=manifest)

    assert verdict.detected_state_model == STATE_MODEL_PER_INSTALL_VOLUME
    assert verdict.pinned_max_replicas == 1
    sqlite_warnings = [w for w in verdict.warnings if w.kind == WARNING_SQLITE_DETECTED]
    assert sqlite_warnings, f"expected sqlite warning, got {verdict.warnings!r}"
    # detected_at should reference the sqlite file
    assert any("sessions.db" in w.detected_at for w in sqlite_warnings)
    # add_postgres offer must be present
    assert [o.kind for o in verdict.upgrade_offers] == ["add_postgres"]
    offer = verdict.upgrade_offers[0]
    assert offer.manifest_patch["runtime"]["state_model"] == "external"
    assert (
        offer.manifest_patch["runtime"]["scaling"]["max_replicas"]
        == DEFAULT_SCALABLE_MAX_REPLICAS
    )


# ---------------------------------------------------------------------------
# check_state_model — stateless happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_state_model_stateless_no_evidence(db, seeded_project):
    """A clean stateless project: no .db files, no startup commands → unbounded."""
    project, project_root = seeded_project
    # Ship an obviously safe file so we know the walk runs but finds nothing.
    (project_root / "README.md").write_text("hello world")

    # Add a container with NO startup_command sniff trigger.
    await _add_container(db, project, name="web", startup_command="node server.js")

    manifest = _stub_manifest(
        state_model="stateless",
        max_replicas=10,
    )

    verdict = await check_state_model(db, project=project, manifest=manifest)

    assert verdict.detected_state_model == STATE_MODEL_STATELESS
    assert verdict.pinned_max_replicas == 10
    assert verdict.warnings == []
    # No upgrade offers — already scalable.
    assert verdict.upgrade_offers == []


# ---------------------------------------------------------------------------
# check_state_model — framework pattern (next dev + .next/cache)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_state_model_framework_pattern(db, seeded_project):
    """``next dev`` + a ``.next/cache`` directory → framework_pattern warning.

    We assert both the file-walk-found dir and the startup-command sniff
    fire, so the verdict carries two warnings of kind framework_pattern
    (one detected_at the relative path, one at the container name).
    """
    project, project_root = seeded_project
    cache_dir = project_root / ".next" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "manifest.json").write_text("{}")

    await _add_container(db, project, name="web", startup_command="next dev -p 3000")

    manifest = _stub_manifest(state_model="per_install_volume", max_replicas=1)

    verdict = await check_state_model(db, project=project, manifest=manifest)

    framework_warnings = [
        w for w in verdict.warnings if w.kind == WARNING_FRAMEWORK_PATTERN
    ]
    assert len(framework_warnings) >= 2, (
        "expected one framework warning from the file scan and one from the "
        f"startup-command sniff, got {framework_warnings!r}"
    )
    # File-scan side: detected_at is the relative directory.
    assert any(".next/cache" in w.detected_at for w in framework_warnings)
    # Command-sniff side: detected_at is the container name.
    assert any(w.detected_at == "web" for w in framework_warnings)
    assert verdict.pinned_max_replicas == 1


# ---------------------------------------------------------------------------
# add_postgres — Secret write + manifest patch + migration helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_postgres_writes_secret_and_patches_manifest(db, seeded_project):
    """add_postgres: stubbed URL + real K8s Secret write + manifest patched.

    The K8s client is a MagicMock so we can assert ``create_namespaced_secret``
    was called with the right args. The manifest YAML is pre-seeded in the
    workspace so we can verify the in-place patch.
    """
    project, project_root = seeded_project

    # Pre-seed an opensail.app.yaml so the patcher writes through.
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
    manifest_path = project_root / "opensail.app.yaml"
    manifest_path.write_text(manifest_yaml)

    # Pre-seed package.json so the migration helper picks ts.
    (project_root / "package.json").write_text("{}")

    # Need a User row passed in — reuse the seeded one.
    user = await db.get(User, project.owner_id)
    assert user is not None

    core_v1 = MagicMock()
    core_v1.create_namespaced_secret = MagicMock(return_value=None)
    core_v1.patch_namespaced_secret = MagicMock(return_value=None)

    result = await add_postgres(db, project=project, user=user, core_v1=core_v1)

    # 1. Secret name is deterministic.
    assert result.secret_name == managed_db_secret_name(project.id)
    assert result.secret_namespace == f"proj-{project.id}"

    # 2. Stub URL points at the sentinel host.
    assert "managed-postgres-pool" in result.connection_url
    assert result.connection_url.startswith("postgresql://")
    assert result.is_stub_provisioner is True

    # 3. K8s Secret was created exactly once.
    core_v1.create_namespaced_secret.assert_called_once()
    create_kwargs = core_v1.create_namespaced_secret.call_args
    assert create_kwargs.kwargs["namespace"] == f"proj-{project.id}"
    body = create_kwargs.kwargs["body"]
    assert body.metadata.name == result.secret_name
    assert "url" in body.string_data
    assert body.string_data["url"] == result.connection_url
    assert body.string_data["host"] == "managed-postgres-pool"

    # 4. Manifest patch shape is correct.
    patch_runtime = result.manifest_patch["runtime"]
    assert patch_runtime["state_model"] == "external"
    assert patch_runtime["scaling"]["max_replicas"] == DEFAULT_SCALABLE_MAX_REPLICAS
    container_env = result.manifest_patch["compute"]["containers"][0]["env"]
    assert container_env["DATABASE_URL"] == f"${{secret:{result.secret_name}/url}}"

    # 5. opensail.app.yaml on disk now contains the merged values.
    import yaml

    with manifest_path.open("r", encoding="utf-8") as f:
        merged = yaml.safe_load(f)
    assert merged["runtime"]["state_model"] == "external"
    assert merged["runtime"]["scaling"]["max_replicas"] == DEFAULT_SCALABLE_MAX_REPLICAS
    assert result.manifest_path == str(manifest_path)

    # 6. Migration helper was written; package.json present → ts variant.
    assert result.migration_script_path is not None
    assert result.migration_script_path.endswith("migrate-from-sqlite.ts")
    assert os.path.exists(result.migration_script_path)
    helper_body = Path(result.migration_script_path).read_text()
    assert "better-sqlite3" in helper_body
    assert "DATABASE_URL" in helper_body

    # 7. Notes call out the stub.
    assert any("STUBBED" in n for n in result.notes)
