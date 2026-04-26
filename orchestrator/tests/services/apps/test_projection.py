"""Tests for the manifest 2026-05 projection service.

Covers:
  * Round-trip: a valid 2026-05 manifest with all six blocks projects to
    the expected row counts and values.
  * Idempotency: calling regenerate twice yields the same row count
    (delete+insert, no append).
  * Old-projection cleanup: a stale projection for the same version is
    fully replaced.
  * Atomicity: an invalid manifest aborts inside the savepoint with no
    partial state — the prior projection (if any) survives.
  * Schema skip: a 2025-01 manifest is a no-op (returns zeroes).

The fixtures spin up an in-memory SQLite database and run
``Base.metadata.create_all``. This intentionally avoids the heavier
postgres-based ``db_session`` fixture in ``tests/apps/conftest.py`` —
projection is a pure SQL service with no Postgres-only features.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing models_automations is what registers the six projection tables on
# Base.metadata. Without this import their CREATE TABLE statements would not
# be emitted by create_all and the test DB would be missing the projection
# schema.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.services.apps import projection


# ---------------------------------------------------------------------------
# Fixtures — fresh in-memory SQLite per-test.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite session with the full app schema installed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        # SQLite needs PRAGMA foreign_keys=ON so the migration's CASCADE FKs
        # actually fire in tests; the projection service still deletes
        # explicitly so this only matters for the test DB hygiene.
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Manifest builders.
# ---------------------------------------------------------------------------


def _full_manifest_2026_05(
    *,
    app_id: str = "com.example.parent",
    version: str = "1.0.0",
    dep_app_id: str | None = None,
) -> dict[str, Any]:
    """Manifest with at least one row in each of the six projection blocks.

    ``dep_app_id`` is the manifest-level app_id of a dependency; the
    matching MarketplaceApp.slug must already exist in the test DB, or
    the projection raises ``DependencyAppNotFound``.
    """
    deps: list[dict[str, Any]] = []
    if dep_app_id:
        deps.append(
            {
                "alias": "child",
                "app_id": dep_app_id,
                "required": True,
                "needs": {"actions": ["a1"], "views": [], "data_resources": []},
            }
        )
    return {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": app_id,
            "name": "Parent App",
            "slug": "parent-app",
            "version": version,
        },
        "runtime": {
            "tenancy_model": "per_install",
            "state_model": "stateless",
            "scaling": {"min_replicas": 0, "max_replicas": 1},
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {"model": "free", "rate_percent": 0, "price_usd": 0},
        },
        "actions": [
            {
                "name": "summarize",
                "description": "Summarize a document",
                "handler": {"kind": "http_post", "container": "web", "path": "/summarize"},
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "timeout_seconds": 30,
                "idempotency": {"kind": "input_hash", "ttl_seconds": 600},
                "required_connectors": ["openai"],
            },
            {
                "name": "list_docs",
                "handler": {"kind": "http_post", "container": "web", "path": "/list"},
            },
        ],
        "views": [
            {
                "name": "dashboard",
                "kind": "full_page",
                "entrypoint": "/dashboard",
                "cache_ttl_seconds": 60,
            }
        ],
        "data_resources": [
            {
                "name": "docs_view",
                "backed_by_action": "list_docs",
                "schema": {"type": "array"},
                "cache_ttl_seconds": 30,
            }
        ],
        "dependencies": deps,
        "connectors": [
            {
                "id": "openai",
                "kind": "api_key",
                "exposure": "proxy",
                "scopes": ["chat.completions"],
                "required": True,
            }
        ],
        "automation_templates": [
            {
                "name": "daily_summary",
                "description": "Summarize new docs each morning",
                "trigger": {"kind": "cron", "expression": "0 9 * * *"},
                "action": {"kind": "app.invoke", "action": "summarize"},
                "is_default_enabled": True,
            }
        ],
    }


def _legacy_2025_01_manifest() -> dict[str, Any]:
    return {
        "manifest_schema_version": "2025-01",
        "app": {
            "id": "com.example.legacy",
            "name": "Legacy",
            "slug": "legacy",
            "version": "0.1.0",
        },
        "compatibility": {
            "studio": {"min": "3.2.0"},
            "manifest_schema": "2025-01",
            "runtime_api": "^1.0",
        },
        "surfaces": [{"kind": "ui", "entrypoint": "index.html"}],
        "state": {"model": "stateless"},
        "billing": {
            "ai_compute": {"payer": "installer"},
            "general_compute": {"payer": "installer"},
            "platform_fee": {"model": "free", "price_usd": 0},
        },
        "listing": {"visibility": "public"},
    }


# ---------------------------------------------------------------------------
# DB helpers.
# ---------------------------------------------------------------------------


async def _seed_marketplace_app(
    db: AsyncSession,
    *,
    slug: str,
    name: str = "Test App",
) -> models.MarketplaceApp:
    app = models.MarketplaceApp(id=uuid.uuid4(), slug=slug, name=name)
    db.add(app)
    await db.flush()
    return app


async def _seed_app_version(
    db: AsyncSession,
    *,
    app: models.MarketplaceApp,
    manifest: dict[str, Any],
) -> models.AppVersion:
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version=manifest["app"]["version"],
        manifest_schema_version=manifest["manifest_schema_version"],
        manifest_json=manifest,
        manifest_hash="sha256:" + ("a" * 64),
        feature_set_hash="fs:test",
    )
    db.add(av)
    await db.flush()
    return av


async def _count_projection_rows(
    db: AsyncSession, app_version_id: uuid.UUID
) -> dict[str, int]:
    """Return per-table counts for one app_version_id (post-flush)."""
    counts = {}
    for label, model in (
        ("actions", models_automations.AppAction),
        ("views", models_automations.AppView),
        ("data_resources", models_automations.AppDataResource),
        ("dependencies", models_automations.AppDependency),
        ("connector_requirements", models_automations.AppConnectorRequirement),
        ("automation_templates", models_automations.AppAutomationTemplate),
    ):
        rows = (
            await db.execute(
                select(model).where(model.app_version_id == app_version_id)
            )
        ).scalars().all()
        counts[label] = len(rows)
    return counts


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_trip_full_manifest_writes_all_six_blocks(db: AsyncSession) -> None:
    parent_app = await _seed_marketplace_app(db, slug="parent-app", name="Parent")
    child_app = await _seed_marketplace_app(db, slug="child-app", name="Child")
    manifest = _full_manifest_2026_05(dep_app_id=child_app.slug)
    av = await _seed_app_version(db, app=parent_app, manifest=manifest)

    result = await projection.regenerate_projection(db, app_version_id=av.id)

    assert result == projection.ProjectionResult(
        actions_count=2,
        views_count=1,
        data_resources_count=1,
        dependencies_count=1,
        connector_requirements_count=1,
        automation_templates_count=1,
    )
    counts = await _count_projection_rows(db, av.id)
    assert counts == {
        "actions": 2,
        "views": 1,
        "data_resources": 1,
        "dependencies": 1,
        "connector_requirements": 1,
        "automation_templates": 1,
    }

    # Verify data_resource resolved its action FK by name.
    list_docs_id = (
        await db.execute(
            select(models_automations.AppAction.id).where(
                models_automations.AppAction.app_version_id == av.id,
                models_automations.AppAction.name == "list_docs",
            )
        )
    ).scalar_one()
    dr = (
        await db.execute(
            select(models_automations.AppDataResource).where(
                models_automations.AppDataResource.app_version_id == av.id
            )
        )
    ).scalar_one()
    assert dr.backed_by_action_id == list_docs_id

    # Verify dependency resolved app_id (manifest string) → MarketplaceApp.id.
    dep = (
        await db.execute(
            select(models_automations.AppDependency).where(
                models_automations.AppDependency.app_version_id == av.id
            )
        )
    ).scalar_one()
    assert dep.child_app_id == child_app.id
    assert dep.alias == "child"
    assert dep.needs_actions == ["a1"]


@pytest.mark.asyncio
async def test_idempotent_regeneration_does_not_duplicate(db: AsyncSession) -> None:
    parent = await _seed_marketplace_app(db, slug="parent-app")
    child = await _seed_marketplace_app(db, slug="child-app")
    manifest = _full_manifest_2026_05(dep_app_id=child.slug)
    av = await _seed_app_version(db, app=parent, manifest=manifest)

    first = await projection.regenerate_projection(db, app_version_id=av.id)
    second = await projection.regenerate_projection(db, app_version_id=av.id)

    # Same counts both times.
    assert first == second
    counts = await _count_projection_rows(db, av.id)
    assert counts["actions"] == 2
    assert counts["views"] == 1
    assert counts["data_resources"] == 1
    assert counts["dependencies"] == 1
    assert counts["connector_requirements"] == 1
    assert counts["automation_templates"] == 1


@pytest.mark.asyncio
async def test_old_projection_rows_are_replaced(db: AsyncSession) -> None:
    parent = await _seed_marketplace_app(db, slug="parent-app")
    av = await _seed_app_version(
        db, app=parent, manifest=_full_manifest_2026_05()
    )

    # Pre-seed a stale projection row for THIS version that has nothing to
    # do with the current manifest. Regeneration must wipe it.
    stale = models_automations.AppAction(
        id=uuid.uuid4(),
        app_version_id=av.id,
        name="stale_action",
        handler={"kind": "http_post", "container": "old"},
    )
    db.add(stale)
    await db.flush()

    result = await projection.regenerate_projection(db, app_version_id=av.id)
    assert result.actions_count == 2

    remaining_names = {
        r.name
        for r in (
            await db.execute(
                select(models_automations.AppAction).where(
                    models_automations.AppAction.app_version_id == av.id
                )
            )
        )
        .scalars()
        .all()
    }
    assert remaining_names == {"summarize", "list_docs"}


@pytest.mark.asyncio
async def test_atomicity_invalid_dependency_aborts_savepoint(
    db: AsyncSession,
) -> None:
    parent = await _seed_marketplace_app(db, slug="parent-app")
    # First seed a valid projection so we can prove it survives the failure.
    av = await _seed_app_version(
        db, app=parent, manifest=_full_manifest_2026_05()
    )
    await projection.regenerate_projection(db, app_version_id=av.id)
    pre_counts = await _count_projection_rows(db, av.id)
    assert pre_counts["actions"] == 2

    # Now mutate manifest_json to reference an unknown dependency app_id.
    # We cannot replace the row (immutable in real life), but the test DB
    # lets us update for the purpose of triggering the error path.
    bad_manifest = _full_manifest_2026_05(dep_app_id="ghost-app-does-not-exist")
    av.manifest_json = bad_manifest
    await db.flush()

    with pytest.raises(projection.DependencyAppNotFound):
        await projection.regenerate_projection(db, app_version_id=av.id)

    # Old projection survives — the savepoint rolled back, OR the dependency
    # check fired before the savepoint opened. Either way, no partial state.
    post_counts = await _count_projection_rows(db, av.id)
    assert post_counts == pre_counts


@pytest.mark.asyncio
async def test_legacy_manifest_skips_projection(db: AsyncSession) -> None:
    parent = await _seed_marketplace_app(db, slug="legacy-app")
    av = await _seed_app_version(
        db, app=parent, manifest=_legacy_2025_01_manifest()
    )

    result = await projection.regenerate_projection(db, app_version_id=av.id)

    assert result == projection.ProjectionResult.empty()
    counts = await _count_projection_rows(db, av.id)
    assert all(c == 0 for c in counts.values())


@pytest.mark.asyncio
async def test_missing_app_version_raises(db: AsyncSession) -> None:
    bogus_id = uuid.uuid4()
    with pytest.raises(projection.AppVersionNotFound):
        await projection.regenerate_projection(db, app_version_id=bogus_id)
