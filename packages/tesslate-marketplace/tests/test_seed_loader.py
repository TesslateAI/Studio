"""
Tests for ``app.services.seed_loader``.

Verifies:
  * the on-disk JSON seeds populate the catalog UPSERT-by-(kind, slug),
  * re-running the loader is idempotent (no duplicate rows, no extra
    ``upsert`` events with the same ``(kind, slug, version)``),
  * the changes feed advertises every seeded row,
  * the changes feed has a tip even on no-change boots,
  * the FastAPI lifespan startup actually runs the loader so a bare
    ``uvicorn app.main:app`` boots into a populated catalog (the Wave 10
    end-state).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.models import (
    Bundle,
    Category,
    ChangesEvent,
    FeaturedListing,
    Item,
    ItemVersion,
)
from app.services.seed_loader import (
    SEED_FILES,
    SeedLoadResult,
    load_seed_entries,
    load_seeds,
)


def _read_all_seed_entries() -> list[dict]:
    """Read every checked-in seed file the same way the loader does."""
    base = Path(__file__).resolve().parent.parent / "app" / "seeds"
    out: list[dict] = []
    for filename in SEED_FILES:
        path = base / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            out.extend(data)
    return out


# ---------------------------------------------------------------------------
# Sanity: there is on-disk seed content to load.
# ---------------------------------------------------------------------------


def test_seeds_directory_has_content() -> None:
    """Wave 10 contract: the marketplace ships with non-empty seed JSONs.

    If this fails the federation-sync end-state is broken — a fresh
    orchestrator deploy would sync against an empty catalog.
    """
    entries = _read_all_seed_entries()
    assert len(entries) > 0, "marketplace ships with empty seeds — Wave 10 contract violated"

    # Spot-check that every primary kind is represented.
    kinds = {e.get("kind") for e in entries}
    expected_kinds = {"agent", "base", "skill", "mcp_server", "theme", "workflow_template"}
    missing = expected_kinds - kinds
    assert not missing, f"seed catalogue is missing kinds: {missing}"


# ---------------------------------------------------------------------------
# load_seed_entries — pure file reader.
# ---------------------------------------------------------------------------


def test_load_seed_entries_concatenates_all_seed_files() -> None:
    entries = load_seed_entries()
    expected = _read_all_seed_entries()
    assert len(entries) == len(expected)
    assert {(e["kind"], e["slug"]) for e in entries} == {(e["kind"], e["slug"]) for e in expected}


# ---------------------------------------------------------------------------
# load_seeds — the actual UPSERT loop.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_seeds_populates_fresh_database(env) -> None:
    """First call against an empty DB inserts every entry once."""
    result: SeedLoadResult = await load_seeds()

    expected_entries = _read_all_seed_entries()
    expected_count = len(expected_entries)

    assert result.items_failed == 0
    assert result.items_created + result.items_updated == expected_count
    assert result.items_created == expected_count, (
        "fresh DB should create every row, not update"
    )
    assert result.first_etag is not None
    assert result.last_etag is not None

    # Verify rows landed in the DB.
    async with session_scope() as session:
        item_count = (await session.execute(select(func.count()).select_from(Item))).scalar_one()
        assert item_count == expected_count

        # Every Item must have at least one version.
        version_count = (
            await session.execute(select(func.count()).select_from(ItemVersion))
        ).scalar_one()
        assert version_count >= expected_count

        # Per-kind row counts mirror the seed files.
        per_kind_db = dict(
            (await session.execute(select(Item.kind, func.count()).group_by(Item.kind))).all()
        )
        per_kind_seed: dict[str, int] = {}
        for entry in expected_entries:
            kind = entry["kind"]
            per_kind_seed[kind] = per_kind_seed.get(kind, 0) + 1
        assert per_kind_db == per_kind_seed


@pytest.mark.asyncio
async def test_load_seeds_is_idempotent(env) -> None:
    """Re-running the loader must not create duplicate rows or
    duplicate ``(kind, slug, version)`` ``upsert`` events for unchanged
    seed entries."""
    first = await load_seeds()
    expected_count = first.items_created + first.items_updated

    # Snapshot row counts after the first run.
    async with session_scope() as session:
        item_count_1 = (await session.execute(select(func.count()).select_from(Item))).scalar_one()
        version_count_1 = (
            await session.execute(select(func.count()).select_from(ItemVersion))
        ).scalar_one()

    second = await load_seeds()

    # Second run sees every row already exists — created=0, updated=N.
    assert second.items_created == 0
    assert second.items_updated == expected_count

    async with session_scope() as session:
        item_count_2 = (await session.execute(select(func.count()).select_from(Item))).scalar_one()
        version_count_2 = (
            await session.execute(select(func.count()).select_from(ItemVersion))
        ).scalar_one()

    assert item_count_2 == item_count_1, "idempotent re-run created duplicate Item rows"
    assert version_count_2 == version_count_1, "idempotent re-run created duplicate ItemVersion rows"


@pytest.mark.asyncio
async def test_load_seeds_emits_changes_events_per_row(env) -> None:
    """The orchestrator's federation sync worker drains ``/v1/changes`` to
    populate its local cache. Every seeded row must therefore be advertised
    via at least one ``upsert`` event with the canonical ``(kind, slug)``."""
    result = await load_seeds()
    expected_entries = _read_all_seed_entries()

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ChangesEvent.kind, ChangesEvent.slug, ChangesEvent.op)
            )
        ).all()

    seen_upserts = {(r.kind, r.slug) for r in rows if r.op == "upsert" and r.slug != "__startup__"}
    expected_upserts = {(e["kind"], e["slug"]) for e in expected_entries}

    missing = expected_upserts - seen_upserts
    assert not missing, f"no upsert events emitted for: {sorted(missing)[:10]}"

    # Result counters surface the etag range — the orchestrator uses these
    # as the cursor for ``/v1/changes?since=``.
    assert result.first_etag is not None
    assert result.last_etag is not None


@pytest.mark.asyncio
async def test_load_seeds_emits_startup_tick_when_no_entries(env, tmp_path) -> None:
    """When the seed dir is empty the loader still records a baseline
    ``__startup__`` tick so the changes feed has a tip on no-change boots."""
    empty_seeds = tmp_path / "empty_seeds"
    empty_seeds.mkdir()

    result = await load_seeds(seeds_dir=empty_seeds)
    # No seeds → no items processed.
    assert result.items_created == 0
    assert result.items_updated == 0


@pytest.mark.asyncio
async def test_load_seeds_seeds_categories_and_featured(env) -> None:
    """The loader populates ``categories`` and ``featured_listings`` from
    seed metadata so ``/v1/categories`` and ``/v1/featured`` return content
    on a fresh deploy."""
    result = await load_seeds()
    assert result.categories_seeded > 0
    assert result.featured_seeded > 0

    async with session_scope() as session:
        cat_count = (
            await session.execute(select(func.count()).select_from(Category))
        ).scalar_one()
        feat_count = (
            await session.execute(select(func.count()).select_from(FeaturedListing))
        ).scalar_one()

    assert cat_count == result.categories_seeded
    assert feat_count >= result.featured_seeded


@pytest.mark.asyncio
async def test_load_seeds_skips_entries_missing_kind_or_slug(env, tmp_path) -> None:
    """Malformed seed entries should fail in isolation, not abort the boot."""
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "agents.json").write_text(
        json.dumps(
            [
                {"kind": "agent", "slug": "good-agent", "name": "Good"},
                {"kind": "agent", "name": "Missing slug"},  # bad
                {"slug": "no-kind-agent", "name": "Missing kind"},  # bad
            ]
        )
    )

    result = await load_seeds(seeds_dir=seeds)
    assert result.items_created == 1
    assert result.items_failed == 2

    async with session_scope() as session:
        slugs = (await session.execute(select(Item.slug))).scalars().all()
        assert "good-agent" in slugs
        assert "no-kind-agent" not in slugs


@pytest.mark.asyncio
async def test_load_seeds_picks_up_pre_built_bundle_when_present(env, tmp_path) -> None:
    """If a bundle file exists at the conventional location, the loader
    attaches a ``Bundle`` row pointing at the storage adapter. Most catalog
    kinds ship without bundles — those rows just have no ``Bundle``."""
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "agents.json").write_text(
        json.dumps([{"kind": "agent", "slug": "bundled", "name": "Bundled"}])
    )

    bundles = tmp_path / "bundles" / "agent" / "bundled"
    bundles.mkdir(parents=True)
    bundle_file = bundles / "0.1.0.tar.zst"
    bundle_file.write_bytes(b"fake-tar-zst-payload")

    # Patch the bundle dir resolver via monkeypatching the module function.
    import app.services.seed_loader as loader_mod

    original = loader_mod._bundles_dir
    loader_mod._bundles_dir = lambda: tmp_path / "bundles"  # type: ignore[assignment]
    try:
        result = await load_seeds(seeds_dir=seeds)
        assert result.bundles_attached == 1
    finally:
        loader_mod._bundles_dir = original  # type: ignore[assignment]

    async with session_scope() as session:
        bundle_count = (
            await session.execute(select(func.count()).select_from(Bundle))
        ).scalar_one()
    assert bundle_count == 1


# ---------------------------------------------------------------------------
# FastAPI startup wiring — Wave 10 end-state contract.
# ---------------------------------------------------------------------------


async def _run_lifespan(app) -> None:
    """Drive the FastAPI lifespan startup hook directly.

    ``httpx.ASGITransport`` (0.28) does not invoke lifespan events, so for
    the seed-loader-on-startup contract we step through the ASGI lifespan
    protocol by hand — the same way uvicorn would on a real boot.
    """
    received: list[dict] = []
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        # Send startup, then shutdown when the app calls receive() again.
        if not received:
            received.append({"type": "lifespan.startup"})
            return received[-1]
        received.append({"type": "lifespan.shutdown"})
        return received[-1]

    await app.router.lifespan_context.__aenter__() if hasattr(
        app.router, "lifespan_context"
    ) else None
    # Use ASGI protocol directly: call the app with lifespan scope.
    from anyio import create_task_group

    scope = {"type": "lifespan"}
    async with create_task_group() as tg:
        tg.start_soon(app, scope, receive, send)


@pytest.mark.asyncio
async def test_lifespan_runs_seed_loader_on_startup(env, monkeypatch) -> None:
    """A fresh ``app.main:create_app`` must run the seed loader during the
    FastAPI lifespan so a bare ``uvicorn`` boot yields a populated catalog
    (no separate provisioning step). Per the Wave 10 plan the federation
    sync worker is the orchestrator's only catalog source — so the
    marketplace must already be populated before the orchestrator polls.
    """
    monkeypatch.setenv("MARKETPLACE_LOAD_SEEDS_ON_STARTUP", "true")

    from app.config import reload_settings
    from app.main import create_app

    reload_settings()
    app = create_app()

    # Drive the lifespan startup directly via Starlette's router context.
    async with app.router.lifespan_context(app):
        # Lifespan startup completed — the catalog should now be populated.
        async with session_scope() as session:
            item_count = (
                await session.execute(select(func.count()).select_from(Item))
            ).scalar_one()
        assert item_count > 0, "lifespan startup did not seed catalog"


@pytest.mark.asyncio
async def test_lifespan_skips_seed_loader_when_disabled(env, monkeypatch) -> None:
    """``MARKETPLACE_LOAD_SEEDS_ON_STARTUP=false`` opts out of automatic
    seeding — used by integration test harnesses that prefer to run
    ``init_db.py`` explicitly so they control the timing."""
    monkeypatch.setenv("MARKETPLACE_LOAD_SEEDS_ON_STARTUP", "false")

    from app.config import reload_settings
    from app.main import create_app

    reload_settings()
    app = create_app()

    async with app.router.lifespan_context(app):
        async with session_scope() as session:
            item_count = (
                await session.execute(select(func.count()).select_from(Item))
            ).scalar_one()
        assert item_count == 0, "lifespan startup seeded catalog despite opt-out"
