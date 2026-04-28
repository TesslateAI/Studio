"""Tests for ``publish_inferrer.infer_draft``.

The inferrer walks a Project's Container / ContainerConnection /
DeploymentCredential rows + ``.tesslate/config.json`` and emits a draft
2026-05 manifest YAML. The YAML carries a ``# Inferred containers``
comment block so the creator sees their compute layout before editing.

Critical invariant: the comment block must be invisible to the YAML
parser. A multi-line ``yaml.safe_dump`` of a container entry produces
``name: backend\\ndirectory: /app\\nport: 3000\\nstart: npm start``;
if only the first line gets the ``#`` prefix the continuation lines
leak into the body and the publisher rejects the manifest with
``additionalProperties: ('directory', 'port', 'start') were
unexpected`` (this is the regression that motivated the test).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models, models_automations  # noqa: F401  -- register tables
from app.database import Base
from app.models import (
    PROJECT_KIND_APP_SOURCE,
    Container,
    ContainerConnection,
    Project,
    Team,
    User,
)
from app.services.apps.publish_inferrer import (
    _yaml_to_comment_block,
    infer_draft,
)


# ---------------------------------------------------------------------------
# Schema 2026-05 — top-level keys the publisher accepts. Anything else at
# the root will 422 with additionalProperties: false.
# ---------------------------------------------------------------------------
ALLOWED_ROOT_KEYS: frozenset[str] = frozenset(
    {
        "manifest_schema_version",
        "app",
        "runtime",
        "billing",
        "surfaces",
        "actions",
        "views",
        "data_resources",
        "dependencies",
        "connectors",
        "automation_templates",
    }
)


# ---------------------------------------------------------------------------
# Fixtures.
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


@pytest_asyncio.fixture
async def project_with_container(db: AsyncSession) -> Project:
    """Project + one Container with the fields that triggered the regression."""
    user_id = uuid.uuid4()
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            name="Inferrer Test",
            username=f"user-{user_id.hex[:10]}",
            slug=f"user-{user_id.hex[:10]}",
        )
    )
    team_id = uuid.uuid4()
    db.add(
        Team(
            id=team_id,
            slug=f"team-{team_id.hex[:10]}",
            name="Inf Team",
            is_personal=True,
            created_by_id=user_id,
        )
    )
    await db.flush()

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name="Test App",
        slug=f"test-app-{project_id.hex[:6]}",
        owner_id=user_id,
        team_id=team_id,
        visibility="team",
        project_kind=PROJECT_KIND_APP_SOURCE,
        volume_id=f"vol-{project_id.hex[:8]}",
    )
    db.add(project)
    await db.flush()

    db.add(
        Container(
            id=uuid.uuid4(),
            project_id=project_id,
            name="backend",
            directory="/app",
            container_name=f"proj-{project_id.hex[:6]}-backend",
            port=3000,
            internal_port=3000,
            startup_command="npm start",
            container_type="base",
            is_primary=True,
        )
    )
    await db.flush()
    return project


# ---------------------------------------------------------------------------
# Unit: _yaml_to_comment_block.
# ---------------------------------------------------------------------------


def test_yaml_to_comment_block_comments_every_line() -> None:
    entry: dict[str, Any] = {
        "name": "backend",
        "directory": "/app",
        "port": 3000,
        "start": "npm start",
    }
    out = _yaml_to_comment_block(entry)
    assert all(line.lstrip().startswith("#") for line in out), (
        f"every line must start with '#', got {out!r}"
    )
    # The list-item dash sits on the first line so the block reads as YAML.
    assert out[0].startswith("#   - "), out
    # Continuation lines align under the dash.
    assert all(line.startswith("#     ") for line in out[1:]), out


def test_yaml_to_comment_block_empty_dict_returns_empty_list() -> None:
    assert _yaml_to_comment_block({}) == []


# ---------------------------------------------------------------------------
# Integration: infer_draft round-trips through yaml.safe_load cleanly.
# ---------------------------------------------------------------------------


async def test_infer_draft_yaml_parses_with_only_allowed_root_keys(
    db: AsyncSession, project_with_container: Project
) -> None:
    draft = await infer_draft(db, project=project_with_container)

    parsed = yaml.safe_load(draft.yaml_str)
    assert isinstance(parsed, dict), f"YAML did not parse to a dict: {parsed!r}"

    leaked = set(parsed.keys()) - ALLOWED_ROOT_KEYS
    assert not leaked, (
        f"hint comment block leaked keys {sorted(leaked)} into the manifest "
        f"body. YAML was:\n{draft.yaml_str}"
    )

    # Sanity: the legacy bug specifically leaked these — assert their absence
    # explicitly so the failure message is unambiguous if it regresses.
    for forbidden in ("directory", "port", "start"):
        assert forbidden not in parsed, (
            f"container field '{forbidden}' leaked as a top-level manifest "
            f"key. YAML was:\n{draft.yaml_str}"
        )


async def test_infer_draft_yaml_preserves_container_hints_as_comments(
    db: AsyncSession, project_with_container: Project
) -> None:
    """The hint block stays visible to humans — it's just hidden from YAML."""
    draft = await infer_draft(db, project=project_with_container)
    assert "# Inferred containers" in draft.yaml_str
    assert "# " in draft.yaml_str  # at least some comment lines
    # Container fields are still readable in the comments — they're just
    # behind '#' so the parser ignores them.
    assert "directory: /app" in draft.yaml_str
    assert "start: npm start" in draft.yaml_str


async def test_infer_draft_loads_config_via_orchestrator_in_k8s_mode(
    db: AsyncSession, project_with_container: Project, monkeypatch
) -> None:
    """When ``get_project_fs_path`` returns None (K8s), the inferrer must
    route the .tesslate/config.json read through ``orchestrator.read_file``
    instead of bailing to ``None``. Regression: pre-fix the K8s path
    short-circuited and every K8s publish surfaced 'config.json not found'
    even when the file existed on the project's PVC."""
    import json

    from app.services.apps import publish_inferrer

    # Force the "no host fs" branch.
    monkeypatch.setattr(publish_inferrer, "get_project_fs_path", lambda _: None)

    config_payload = json.dumps(
        {
            "primaryApp": "frontend",
            "apps": {
                "frontend": {
                    "name": "frontend",
                    "framework": "vite",
                    "dir": "/app",
                    "start": "npm run dev",
                    "port": 5173,
                }
            },
            "infrastructure": {},
            "connections": [],
        }
    )

    class _FakeOrchestrator:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def read_file(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("file_path") == ".tesslate/config.json":
                return config_payload
            return None

    fake = _FakeOrchestrator()
    # Patch the lazily imported get_orchestrator inside _load_tesslate_config.
    import app.services.orchestration as orchestration_module

    monkeypatch.setattr(
        orchestration_module, "get_orchestrator", lambda *a, **kw: fake
    )

    draft = await infer_draft(db, project=project_with_container)

    assert fake.calls, "orchestrator.read_file was never called"
    call = fake.calls[0]
    assert call["file_path"] == ".tesslate/config.json"
    assert call["project_slug"] == project_with_container.slug
    assert call["volume_id"] == project_with_container.volume_id

    # The "config.json not found" warning is suppressed when the config
    # loads successfully — assert the warning is ABSENT.
    not_found = [c for c in draft.checklist if c.id == "config_hint"]
    assert not_found == [], (
        f"config.json was loaded via orchestrator but checklist still "
        f"reports it missing: {[(c.id, c.status, c.title) for c in not_found]}"
    )


async def test_infer_draft_yaml_with_connection_does_not_leak_kind(
    db: AsyncSession, project_with_container: Project
) -> None:
    """Connections also use the multi-line dump path — make sure neither
    'from'/'to'/'kind' leak into the parsed body."""
    # Add a second container + a connection.
    second_id = uuid.uuid4()
    db.add(
        Container(
            id=second_id,
            project_id=project_with_container.id,
            name="frontend",
            directory="/app/frontend",
            container_name=f"proj-{project_with_container.id.hex[:6]}-frontend",
            port=5173,
            internal_port=5173,
            startup_command="npm run dev",
            container_type="base",
        )
    )
    await db.flush()
    # Find the first container's id.
    first = (
        await db.execute(  # type: ignore[attr-defined]
            __import__("sqlalchemy").select(Container).where(
                Container.project_id == project_with_container.id,
                Container.name == "backend",
            )
        )
    ).scalar_one()
    db.add(
        ContainerConnection(
            id=uuid.uuid4(),
            project_id=project_with_container.id,
            source_container_id=first.id,
            target_container_id=second_id,
            connector_type="http_api",
        )
    )
    await db.flush()

    draft = await infer_draft(db, project=project_with_container)
    parsed = yaml.safe_load(draft.yaml_str)
    leaked = set(parsed.keys()) - ALLOWED_ROOT_KEYS
    assert not leaked, (
        f"connection hint leaked keys {sorted(leaked)}. YAML was:\n{draft.yaml_str}"
    )
    for forbidden in ("from", "to", "kind"):
        assert forbidden not in parsed
