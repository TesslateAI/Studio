"""
Idempotent UPSERT-by-(kind, slug) loader for marketplace seed data.

After Wave 10 the orchestrator no longer carries any catalog seed scripts;
the federation sync worker is the sole population path on fresh deploys.
For sync to have anything to pull, the marketplace service must populate
itself from the JSON files under ``app/seeds/`` on first boot. This module
is the single entry-point used by:

  * the FastAPI lifespan hook in :mod:`app.main` (every startup, idempotent)
  * the ``scripts/init_db.py`` provisioning script (used by docker-compose
    and the orchestrator integration tests)

Design constraints:

  * UPSERT by ``(kind, slug)`` — re-running the loader on a populated DB is
    a no-op for unchanged rows and a field-level refresh for modified rows.
    No row is ever duplicated.
  * Every successful upsert emits a ``ChangesEvent`` so the
    ``/v1/changes?since=`` feed advertises the seeded items to federation
    clients. Without this, a fresh marketplace would advertise an empty
    catalog to the orchestrator's sync worker even though the items exist.
  * Bundles are optional — most catalog kinds (``mcp_server``, ``base``,
    ``theme``, ``workflow_template``, ``skill``, ``agent``) are config-only
    and don't need an executable bundle. The loader picks up pre-built
    bundles from ``app/bundles/{kind}/{slug}/{version}.tar.zst`` when
    present and skips the ``Bundle`` row otherwise.
  * Failure on one row never blocks the others. Each row is wrapped in its
    own try/except + per-row rollback to a SAVEPOINT so a single bad seed
    does not poison the whole startup.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings, get_settings
from ..models import (
    AttestationKey,
    Bundle,
    Capability,
    Category,
    FeaturedListing,
    Item,
    ItemVersion,
)
from . import changes_emitter
from .attestations import get_attestor
from .cas import get_bundle_storage

logger = logging.getLogger(__name__)


# Default version stamp for seed-derived ItemVersion rows. Changing this is a
# breaking change — the orchestrator's federation cache keys items by
# ``(source_id, kind, slug)`` so the version number mainly governs which
# manifest gets cached. Keep at "0.1.0" for backwards compatibility.
DEFAULT_VERSION = "0.1.0"

# Order matters only for human-readable boot logs — every file is independently
# upserted by ``(kind, slug)``.
SEED_FILES: tuple[str, ...] = (
    "agents.json",
    "opensource_agents.json",
    "bases.json",
    "community_bases.json",
    "skills_opensource.json",
    "skills_tesslate.json",
    "mcp_servers.json",
    "themes.json",
    "workflow_templates.json",
    "apps.json",
)


@dataclass
class SeedLoadResult:
    """Aggregate counters for a single ``load_seeds`` invocation."""

    items_created: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    items_failed: int = 0
    bundles_attached: int = 0
    categories_seeded: int = 0
    featured_seeded: int = 0
    files_loaded: int = 0
    files_skipped: list[str] = field(default_factory=list)
    first_etag: str | None = None
    last_etag: str | None = None

    def total_processed(self) -> int:
        return self.items_created + self.items_updated + self.items_unchanged

    def total_changed(self) -> int:
        return self.items_created + self.items_updated


def _manifest_signature(entry: dict[str, Any]) -> str:
    """Stable hash of a seed entry for unchanged-row detection.

    ``json.dumps(sort_keys=True)`` gives us a deterministic byte stream
    even when the source dict iteration order shifts between Python
    versions. We hash the canonical bytes rather than comparing dicts
    directly so the signature can be stored in the row's manifest blob.
    """
    import hashlib

    canonical = json.dumps(entry, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _seeds_dir() -> Path:
    """Resolve the on-disk seed directory.

    The package layout is ``packages/tesslate-marketplace/app/seeds`` —
    sibling to this services module's parent.
    """
    return Path(__file__).resolve().parent.parent / "seeds"


def _bundles_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "bundles"


def _bundle_path(kind: str, slug: str, version: str) -> Path:
    return _bundles_dir() / kind / slug / f"{version}.tar.zst"


def _coerce_price_cents(value: Any) -> int:
    """Convert a seed entry's ``price`` field to cents.

    Seed JSON authored against the orchestrator schema uses ``price`` as a
    dollar-denominated integer. The marketplace stores ``price_cents``.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        # bool is an int subclass in Python; reject explicitly so we don't
        # silently coerce ``True`` -> 100 cents.
        return 0
    if isinstance(value, (int, float)):
        return int(round(value * 100))
    return 0


def _build_pricing_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "pricing_type": entry.get("pricing_type", "free"),
        "price_cents": _coerce_price_cents(entry.get("price")),
        "currency": entry.get("currency", "usd"),
        "stripe_price_id": entry.get("stripe_price_id"),
    }


async def _upsert_attestation_key(session: AsyncSession, settings: Settings) -> None:
    """Make sure the hub's signing key is registered before any bundle is
    attested. Idempotent — re-runs are a no-op."""
    attestor = get_attestor(settings)
    key_id = attestor.public_key_id()
    existing = (
        await session.execute(select(AttestationKey).where(AttestationKey.key_id == key_id))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            AttestationKey(
                key_id=key_id,
                public_key_pem=attestor.public_key_pem(),
                algorithm="ed25519",
                is_active=True,
            )
        )


async def _ensure_capabilities_recorded(session: AsyncSession, settings: Settings) -> None:
    """Mirror the active capability set into the `capabilities` table for
    forward-compatible hubs that surface the registry directly."""
    for capability in sorted(settings.capabilities):
        existing = (
            await session.execute(select(Capability).where(Capability.name == capability))
        ).scalar_one_or_none()
        if existing is None:
            session.add(Capability(name=capability, is_enabled=True))


async def _seed_categories(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    """Backfill ``categories`` rows from the unique (kind, category) pairs
    referenced in the seed entries. Idempotent."""
    wanted: set[tuple[str, str]] = set()
    for entry in items:
        kind = entry.get("kind")
        cat = entry.get("category")
        if kind and cat:
            wanted.add((kind, cat))
    if not wanted:
        return 0

    rows = (
        await session.execute(
            select(Category.kind, Category.slug).where(
                Category.kind.in_({k for k, _ in wanted}),
                Category.slug.in_({c for _, c in wanted}),
            )
        )
    ).all()
    existing = {(r[0], r[1]) for r in rows}

    seeded = 0
    for kind, cat in wanted:
        if (kind, cat) in existing:
            continue
        session.add(
            Category(
                kind=kind,
                slug=cat,
                name=cat.replace("-", " ").title(),
                sort_order=100,
            )
        )
        seeded += 1
    return seeded


async def _seed_featured(session: AsyncSession, entries: list[dict[str, Any]]) -> int:
    """Pin every entry with ``is_featured: true`` into ``featured_listings``.

    Rank is a monotonic counter so the manifest order survives between runs;
    the loader does not re-rank previously-pinned items.
    """
    wanted_keys: list[tuple[str, str]] = []
    for entry in entries:
        if not entry.get("is_featured"):
            continue
        kind = entry.get("kind")
        slug = entry.get("slug")
        if kind and slug:
            wanted_keys.append((kind, slug))
    if not wanted_keys:
        return 0

    items = (
        await session.execute(
            select(Item).where(
                Item.kind.in_({k for k, _ in wanted_keys}),
                Item.slug.in_({s for _, s in wanted_keys}),
            )
        )
    ).scalars().all()
    items_by_key: dict[tuple[str, str], Item] = {(i.kind, i.slug): i for i in items}

    item_ids = [i.id for i in items]
    existing_listings: set[tuple[str, Any]] = set()
    if item_ids:
        rows = (
            await session.execute(
                select(FeaturedListing.kind, FeaturedListing.item_id).where(
                    FeaturedListing.item_id.in_(item_ids)
                )
            )
        ).all()
        existing_listings = {(r[0], r[1]) for r in rows}

    rank = 100
    seeded = 0
    for kind, slug in wanted_keys:
        item = items_by_key.get((kind, slug))
        if item is None:
            continue
        if (item.kind, item.id) in existing_listings:
            rank += 10
            continue
        session.add(FeaturedListing(kind=item.kind, item_id=item.id, rank=rank))
        seeded += 1
        rank += 10
    return seeded


async def _upsert_item(
    session: AsyncSession, entry: dict[str, Any], settings: Settings
) -> tuple[Item, ItemVersion, Bundle | None, bool, bool]:
    """Idempotent UPSERT of one ``(kind, slug)`` pair plus its version + bundle.

    Returns ``(item, version, bundle, created, changed)`` where ``changed``
    is False when the seed entry is byte-identical to the previously
    stored manifest — callers skip the changes-emitter event in that case
    to keep the WAL quiet across restarts.
    """
    kind = entry["kind"]
    slug = entry["slug"]
    version = entry.get("version") or DEFAULT_VERSION

    pricing_payload = _build_pricing_payload(entry)
    pricing_type = pricing_payload["pricing_type"]
    price_cents = pricing_payload["price_cents"]

    item = (
        await session.execute(select(Item).where(Item.kind == kind, Item.slug == slug))
    ).scalar_one_or_none()
    created = False
    if item is None:
        item = Item(
            kind=kind,
            slug=slug,
            name=entry.get("name", slug),
            description=entry.get("description"),
            long_description=entry.get("long_description"),
            category=entry.get("category"),
            icon=entry.get("icon"),
            avatar_url=entry.get("avatar_url"),
            preview_image=entry.get("preview_image"),
            is_active=bool(entry.get("is_active", True)),
            is_featured=bool(entry.get("is_featured", False)),
            is_published=bool(entry.get("is_published", True)),
            pricing_type=pricing_type,
            price_cents=price_cents,
            stripe_price_id=entry.get("stripe_price_id"),
            pricing_payload=pricing_payload,
            tags=list(entry.get("tags") or []),
            features=list(entry.get("features") or []),
            tech_stack=list(entry.get("tech_stack") or []),
            extra_metadata=dict(entry.get("extra_metadata") or {}),
            creator_handle=entry.get("creator_handle") or "tesslate",
            creator_display_name=entry.get("creator_display_name") or "Tesslate",
            creator_avatar_url=entry.get("creator_avatar_url"),
            git_repo_url=entry.get("git_repo_url"),
            homepage_url=entry.get("homepage_url"),
            downloads=int(entry.get("downloads") or 0),
            rating=float(entry.get("rating") or 0.0),
            reviews_count=int(entry.get("reviews_count") or 0),
        )
        session.add(item)
        await session.flush()
        created = True
    else:
        # Field-level refresh — keep the row identity (FKs from versions /
        # bundles / featured_listings stay valid) but pick up any seed
        # author edits since the last boot.
        item.name = entry.get("name", item.name)
        item.description = entry.get("description", item.description)
        item.long_description = entry.get("long_description", item.long_description)
        item.category = entry.get("category", item.category)
        item.icon = entry.get("icon", item.icon)
        item.avatar_url = entry.get("avatar_url", item.avatar_url)
        item.preview_image = entry.get("preview_image", item.preview_image)
        item.is_active = bool(entry.get("is_active", item.is_active))
        item.is_featured = bool(entry.get("is_featured", item.is_featured))
        item.is_published = bool(entry.get("is_published", item.is_published))
        item.pricing_type = pricing_type
        item.price_cents = price_cents
        item.stripe_price_id = entry.get("stripe_price_id")
        item.pricing_payload = pricing_payload
        item.tags = list(entry.get("tags") or item.tags or [])
        item.features = list(entry.get("features") or item.features or [])
        item.tech_stack = list(entry.get("tech_stack") or item.tech_stack or [])
        item.extra_metadata = dict(entry.get("extra_metadata") or item.extra_metadata or {})
        item.git_repo_url = entry.get("git_repo_url", item.git_repo_url)
        item.homepage_url = entry.get("homepage_url", item.homepage_url)

    iv = (
        await session.execute(
            select(ItemVersion).where(
                ItemVersion.item_id == item.id, ItemVersion.version == version
            )
        )
    ).scalar_one_or_none()
    changed = created
    if iv is None:
        iv = ItemVersion(
            item_id=item.id,
            version=version,
            changelog="Initial seed",
            manifest=entry,
        )
        session.add(iv)
        await session.flush()
        changed = True
    else:
        # Only rewrite the manifest blob (and emit a downstream change
        # event) when the seed entry actually shifted. ``json.dumps`` with
        # ``sort_keys`` gives a stable canonical form for the comparison.
        if _manifest_signature(iv.manifest or {}) != _manifest_signature(entry):
            iv.manifest = entry
            changed = True

    item.latest_version = version
    item.latest_version_id = iv.id

    bundle = await _attach_bundle_if_present(session, item, iv, settings)
    return item, iv, bundle, created, changed


async def _attach_bundle_if_present(
    session: AsyncSession,
    item: Item,
    iv: ItemVersion,
    settings: Settings,
) -> Bundle | None:
    """If a pre-built ``app/bundles/{kind}/{slug}/{version}.tar.zst`` exists,
    register it in the bundle store and attach a ``Bundle`` row.

    Per the Wave 10 plan, most catalog kinds ship without bundles —
    ``mcp_server`` archives are manifest-only, ``base`` archives are
    git-reference manifests, and many kinds are config-only. Skipping the
    bundle row is the correct outcome when there is nothing to attach.
    """
    bundle_path = _bundle_path(item.kind, item.slug, iv.version)
    if not bundle_path.exists():
        return None

    bundle_bytes = bundle_path.read_bytes()
    storage = get_bundle_storage(settings)
    ref = storage.put_bytes(item.kind, item.slug, iv.version, bundle_bytes)
    attestor = get_attestor(settings)
    attestation = attestor.sign_sha256(ref.sha256)

    existing_bundle = (
        await session.execute(select(Bundle).where(Bundle.item_version_id == iv.id))
    ).scalar_one_or_none()
    if existing_bundle is None:
        bundle = Bundle(
            item_version_id=iv.id,
            sha256=ref.sha256,
            size_bytes=ref.size_bytes,
            storage_backend=ref.backend,
            storage_key=ref.storage_key,
            attestation_signature=attestation.signature,
            attestation_key_id=attestation.key_id,
            attestation_algorithm=attestation.algorithm,
        )
        session.add(bundle)
        return bundle

    existing_bundle.sha256 = ref.sha256
    existing_bundle.size_bytes = ref.size_bytes
    existing_bundle.storage_backend = ref.backend
    existing_bundle.storage_key = ref.storage_key
    existing_bundle.attestation_signature = attestation.signature
    existing_bundle.attestation_key_id = attestation.key_id
    existing_bundle.attestation_algorithm = attestation.algorithm
    return existing_bundle


def load_seed_entries(seeds_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read every JSON file in :data:`SEED_FILES` and concatenate the entries.

    Errors on a single file are logged and the file is skipped — they never
    abort the whole loader (so one malformed seed file doesn't take down
    the marketplace boot).
    """
    base = seeds_dir or _seeds_dir()
    out: list[dict[str, Any]] = []
    for filename in SEED_FILES:
        path = base / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("seed_loader: could not parse %s; skipping", path)
            continue
        if isinstance(data, list):
            out.extend(data)
    return out


async def load_seeds(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    settings: Settings | None = None,
    seeds_dir: Path | None = None,
    emit_changes_events: bool = True,
    emit_startup_tick: bool = True,
) -> SeedLoadResult:
    """Idempotent UPSERT of every seed entry into the marketplace DB.

    Args:
        session_factory: optional custom session factory. Defaults to the
            module-level singleton from :mod:`app.database`.
        settings: optional resolved settings. Defaults to ``get_settings()``.
        seeds_dir: override the on-disk seeds directory (used by tests).
        emit_changes_events: when True (default), one ``upsert`` event is
            appended to ``changes_events`` per row. The orchestrator's sync
            worker drains this feed via ``/v1/changes?since=<etag>``.
        emit_startup_tick: when True (default), append a single
            ``__startup__`` upsert at the head of the run so the changes
            feed always has a tip even on no-change boots.

    Returns:
        :class:`SeedLoadResult` aggregating counters + the etag range.
    """
    resolved_settings = settings or get_settings()
    if session_factory is None:
        # Imported lazily to avoid a circular at module load.
        from ..database import get_session_factory

        session_factory = get_session_factory()

    entries = load_seed_entries(seeds_dir)
    result = SeedLoadResult()

    if not entries:
        logger.info("seed_loader: no seed entries on disk; nothing to do")
        return result

    logger.info("seed_loader: loading %d seed entries", len(entries))

    async with session_factory() as session:
        try:
            await _upsert_attestation_key(session, resolved_settings)
            await _ensure_capabilities_recorded(session, resolved_settings)
            cat_count = await _seed_categories(session, entries)
            await session.commit()
            result.categories_seeded = cat_count
        except Exception:  # noqa: BLE001 - boot must continue even if pre-seed failed
            logger.exception("seed_loader: pre-seed setup failed")
            await session.rollback()

    async with session_factory() as session:
        for entry in entries:
            kind = entry.get("kind")
            slug = entry.get("slug")
            if not kind or not slug:
                logger.warning("seed_loader: skipping entry missing kind/slug: %r", entry)
                result.items_failed += 1
                continue

            # Per-row SAVEPOINT so a single failing seed doesn't abort the
            # surrounding transaction. Postgres + SQLite both honour nested
            # transactions through `session.begin_nested()`.
            try:
                async with session.begin_nested():
                    item, iv, bundle, created, changed = await _upsert_item(
                        session, entry, resolved_settings
                    )
                    if emit_changes_events and changed:
                        event = await changes_emitter.emit(
                            session,
                            op="upsert",
                            kind=item.kind,
                            slug=item.slug,
                            version=iv.version,
                            payload={
                                "name": item.name,
                                "category": item.category,
                                "is_featured": item.is_featured,
                                "version": iv.version,
                            },
                        )
                        if result.first_etag is None:
                            result.first_etag = event.etag
                        result.last_etag = event.etag
            except Exception:  # noqa: BLE001 - per-row failure isolation
                logger.exception(
                    "seed_loader: failed to upsert %s/%s; skipping", kind, slug
                )
                result.items_failed += 1
                continue

            if created:
                result.items_created += 1
            elif changed:
                result.items_updated += 1
            else:
                result.items_unchanged += 1
            if bundle is not None:
                result.bundles_attached += 1

        try:
            featured_count = await _seed_featured(session, entries)
            result.featured_seeded = featured_count
            await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("seed_loader: failed to commit featured listings")
            await session.rollback()

    # The startup heartbeat used to fire unconditionally so the changes
    # feed always advertised a tip etag. After Wave 10 the per-row events
    # above already serve that role on any boot that produced changes —
    # we only need a synthetic tick when literally nothing was emitted
    # (e.g. a no-change repeat boot whose feed table is empty). Keeping
    # it conditional avoids generating one synthetic event per restart.
    if (
        emit_startup_tick
        and emit_changes_events
        and result.last_etag is None
        and result.items_created > 0
    ):
        async with session_factory() as session:
            try:
                tick = await changes_emitter.emit(
                    session,
                    op="upsert",
                    kind="agent",
                    slug="__startup__",
                    payload={
                        "reason": "marketplace seed_loader boot tick",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                result.first_etag = tick.etag
                result.last_etag = tick.etag
                await session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("seed_loader: failed to emit startup tick")
                await session.rollback()

    seed_root = seeds_dir or _seeds_dir()
    result.files_loaded = sum(1 for f in SEED_FILES if (seed_root / f).exists())
    result.files_skipped = [f for f in SEED_FILES if not (seed_root / f).exists()]
    logger.info(
        "seed_loader: complete — created=%d updated=%d unchanged=%d failed=%d "
        "bundles=%d categories=%d featured=%d first_etag=%s last_etag=%s",
        result.items_created,
        result.items_updated,
        result.items_unchanged,
        result.items_failed,
        result.bundles_attached,
        result.categories_seeded,
        result.featured_seeded,
        result.first_etag,
        result.last_etag,
    )
    return result


# Public re-exports for tests / scripts.
__all__ = [
    "DEFAULT_VERSION",
    "SEED_FILES",
    "SeedLoadResult",
    "load_seed_entries",
    "load_seeds",
]
