"""Tests for ``publish_version`` against the 2026-05 manifest schema.

Why this file exists
--------------------
The legacy publisher tests in ``tests/apps/test_publisher_installer.py`` only
cover 2025-01 manifests, which carry ``compatibility`` and ``listing`` blocks
on the typed Pydantic mirror. 2026-05 dropped both blocks (per the App Runtime
Contract). Reading those fields off the typed mirror raised AttributeError on
every 2026-05 publish — and the inferrer in
``services/apps/publish_inferrer.py`` only emits 2026-05 manifests, so the
"Publish as App" toolbar button was unreachable for new content. This file
exercises the publish path against a 2026-05 manifest end-to-end so the
typed-vs-raw read regressions stay caught.

Strategy
--------
In-memory SQLite + StaticPool with the full ``Base.metadata.create_all``
(matching the pattern in ``tests/services/apps/test_publish_checker.py``).
A tiny fake Hub records ``publish_bundle`` calls and returns a fixed digest.
``publish_version`` is exercised directly because that is where the
schema-shape coupling lives.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from copy import deepcopy
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata
# so create_all picks them up. Same import dance the publish_checker tests use.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.models import (
    PROJECT_KIND_APP_SOURCE,
    AppSubmission,
    AppVersion,
    MarketplaceApp,
    Project,
    Team,
    User,
)
from app.services.apps import publisher
from app.services.apps.publisher import _coerce_forkable


class _FakeHub:
    """Records ``publish_bundle`` calls and returns a fixed sha256 digest."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hash = "sha256:" + ("a" * 64)

    async def publish_bundle(
        self,
        *,
        volume_id: str,
        app_id: str,
        version: str,
        timeout: float = 600.0,
    ) -> str:
        self.calls.append(
            {"volume_id": volume_id, "app_id": app_id, "version": version}
        )
        return self._hash


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
    maker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_project(db: AsyncSession):
    """Seed (User, Team, Project) with ``project_kind=app_source`` + a
    non-null ``volume_id`` (both required by the publisher)."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"u-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=False,
        name="Pub Test",
        username=f"user-{user_id.hex[:10]}",
        slug=f"user-{user_id.hex[:10]}",
    )
    db.add(user)

    team_id = uuid.uuid4()
    team = Team(
        id=team_id,
        slug=f"team-{team_id.hex[:10]}",
        name="Pub Team",
        is_personal=True,
        created_by_id=user_id,
    )
    db.add(team)
    await db.flush()

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name="Source",
        slug=f"src-{project_id.hex[:8]}",
        owner_id=user_id,
        team_id=team_id,
        visibility="team",
        project_kind=PROJECT_KIND_APP_SOURCE,
        volume_id=f"vol-{project_id.hex[:8]}",
    )
    db.add(project)
    await db.flush()

    return user_id, project


def _minimal_2026_manifest(
    *,
    version: str = "0.1.0",
    slug: str = "hello-2026",
    forkable: bool | None = False,
    include_slug: bool = True,
) -> dict[str, Any]:
    """Smallest 2026-05 manifest publish_version accepts.

    Optional blocks (surfaces / actions / views / data_resources /
    dependencies / connectors / automation_templates) are all omitted so
    the parser uses its empty-list defaults — no extra surface area for the
    publish path to trip over.
    """
    app_block: dict[str, Any] = {
        "id": f"com.example.{slug}",
        "name": "Hello 2026 App",
        "version": version,
    }
    if include_slug:
        app_block["slug"] = slug
    if forkable is not None:
        app_block["forkable"] = forkable
    return {
        "manifest_schema_version": "2026-05",
        "app": app_block,
        "runtime": {
            "tenancy_model": "per_install",
            "state_model": "stateless",
            "scaling": {
                "min_replicas": 0,
                "max_replicas": 1,
                "target_concurrency": 10,
                "idle_timeout_seconds": 600,
            },
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {
                "rate_percent": 0,
                "model": "free",
                "price_usd": 0,
                "trial_days": 0,
            },
        },
    }


# ---------------------------------------------------------------------------
# Pure unit: forkable coercion (no DB).
# ---------------------------------------------------------------------------


def test_coerce_forkable_true_bool() -> None:
    assert _coerce_forkable(True) == "true"


def test_coerce_forkable_false_bool() -> None:
    assert _coerce_forkable(False) == "no"


@pytest.mark.parametrize("value", ["true", "restricted", "no"])
def test_coerce_forkable_valid_string_passthrough(value: str) -> None:
    assert _coerce_forkable(value) == value


@pytest.mark.parametrize("value", [None, "", "yes", 0, 1, 1.0, []])
def test_coerce_forkable_falls_back_to_restricted(value: Any) -> None:
    assert _coerce_forkable(value) == "restricted"


# ---------------------------------------------------------------------------
# Integration: 2026-05 manifest → publish_version end to end.
# ---------------------------------------------------------------------------


async def test_publish_2026_05_minimal_manifest_succeeds(
    db: AsyncSession,
    seeded_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke: a minimal 2026-05 manifest round-trips through publish_version
    and creates the expected MarketplaceApp / AppVersion / AppSubmission rows.

    Without auto-approve the AppVersion lands in ``pending_stage1`` and the
    AppSubmission in ``stage0`` — same baseline as the 2025-01 happy path.
    """
    monkeypatch.delenv("TSL_APPS_DEV_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("TSL_APPS_SKIP_APPROVAL", raising=False)

    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest()

    result = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    assert hub.calls == [
        {
            "volume_id": project.volume_id,
            "app_id": str(result.app_id),
            "version": "0.1.0",
        }
    ]

    app = await db.get(MarketplaceApp, result.app_id)
    assert app is not None
    assert app.slug == "hello-2026"
    assert app.creator_user_id == user_id
    # 2026-05 manifests have no listing block → publisher defaults to "private".
    assert app.visibility == "private"
    # forkable: false (bool) coerces to "no" (column enum string).
    assert app.forkable == "no"

    av = await db.get(AppVersion, result.app_version_id)
    assert av is not None
    assert av.manifest_schema_version == "2026-05"
    assert av.bundle_hash == result.bundle_hash
    assert av.required_features == []
    assert av.approval_state == "pending_stage1"

    sub = await db.get(AppSubmission, result.submission_id)
    assert sub is not None
    assert sub.stage == "stage0"


async def test_publish_2026_05_forkable_true_maps_to_string(
    db: AsyncSession, seeded_project
) -> None:
    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest(forkable=True)

    result = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    app = await db.get(MarketplaceApp, result.app_id)
    assert app is not None
    assert app.forkable == "true"


async def test_publish_2026_05_forkable_false_maps_to_string(
    db: AsyncSession, seeded_project
) -> None:
    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest(forkable=False)

    result = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    app = await db.get(MarketplaceApp, result.app_id)
    assert app is not None
    assert app.forkable == "no"


async def test_publish_2026_05_no_listing_defaults_visibility_private(
    db: AsyncSession,
    seeded_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 2026-05 schema rejects a top-level ``listing`` block
    (``additionalProperties: false``). Without auto-approve, the
    publisher must default ``MarketplaceApp.visibility`` to ``private``."""
    monkeypatch.delenv("TSL_APPS_DEV_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("TSL_APPS_SKIP_APPROVAL", raising=False)

    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest()

    result = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    app = await db.get(MarketplaceApp, result.app_id)
    assert app is not None
    assert app.visibility == "private"


async def test_publish_2026_05_no_compatibility_block_uses_top_level_schema(
    db: AsyncSession, seeded_project
) -> None:
    """2026-05 dropped the compatibility block entirely. The publisher must
    derive the schema-version string fed to compatibility.check from the
    top-level ``manifest_schema_version`` field rather than:

    1. Raising AttributeError trying to read ``manifest.compatibility.*``
       off the typed mirror (the original bug).
    2. Treating the missing block as an empty schema string and rejecting
       the publish as ``unsupported_manifest_schema``.
    """
    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest()

    result = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    av = await db.get(AppVersion, result.app_version_id)
    assert av is not None
    assert av.manifest_schema_version == "2026-05"
    assert av.required_features == []


async def test_publish_2026_05_omitted_slug_derived_from_app_id(
    db: AsyncSession, seeded_project
) -> None:
    """2026-05 makes ``app.slug`` optional. Publisher must still produce a
    non-empty slug — derived from the last segment of ``app.id`` — so the
    NOT-NULL + UNIQUE column always has a value."""
    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest(slug="derive-me", include_slug=False)

    result = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    app = await db.get(MarketplaceApp, result.app_id)
    assert app is not None
    # app.id was com.example.derive-me → derived slug is "derive-me".
    assert app.slug == "derive-me"


async def test_publish_2026_05_duplicate_version_rejected(
    db: AsyncSession, seeded_project
) -> None:
    """Republishing the same ``(app_id, version)`` raises
    DuplicateVersionError on the 2026-05 path — parity with the existing
    2025-01 duplicate test in ``test_publisher_installer.py``."""
    user_id, project = seeded_project
    hub = _FakeHub()
    manifest = _minimal_2026_manifest()

    first = await publisher.publish_version(
        db,
        creator_user_id=user_id,
        project_id=project.id,
        manifest_source=manifest,
        hub_client=hub,
    )

    with pytest.raises(publisher.DuplicateVersionError):
        await publisher.publish_version(
            db,
            creator_user_id=user_id,
            project_id=project.id,
            manifest_source=deepcopy(manifest),
            hub_client=hub,
            app_id=first.app_id,
        )
