"""
Initialise the marketplace database from scratch:

1. Create every declared table.
2. Run the seed extractor against the orchestrator (if available + JSON
   seeds aren't present yet).
3. Build seed bundles into `app/bundles/`.
4. Insert items + versions + bundle records.
5. Emit the corresponding `upsert` events into the changes feed.

Idempotent — safe to re-run; existing rows are upserted by `(kind, slug)`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure project root is on path before importing the app package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.database import create_all, get_session_factory  # noqa: E402
from app.models import (  # noqa: E402
    ApiToken,
    AttestationKey,
    Bundle,
    Capability,
    Category,
    FeaturedListing,
    Item,
    ItemVersion,
)
from app.services import changes_emitter  # noqa: E402
from app.services.attestations import get_attestor  # noqa: E402
from app.services.auth import hash_token  # noqa: E402
from app.services.cas import get_bundle_storage  # noqa: E402

logger = logging.getLogger("init_db")

SEED_FILES = (
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

DEFAULT_VERSION = "0.1.0"


def _seed_path(name: str) -> Path:
    return ROOT / "app" / "seeds" / name


def _bundle_path(kind: str, slug: str, version: str) -> Path:
    return ROOT / "app" / "bundles" / kind / slug / f"{version}.tar.zst"


async def _ensure_seeds_present() -> None:
    if not _seed_path("agents.json").exists():
        # Run the extractor against the orchestrator
        orch_seeds = ROOT.parent.parent / "orchestrator" / "app" / "seeds"
        if not orch_seeds.is_dir():
            logger.warning("no seed JSONs and no orchestrator seeds dir; skipping seed extraction")
            return
        logger.info("running seed extractor against %s", orch_seeds)
        from scripts import extract_seeds_from_orchestrator as ext  # noqa: WPS433

        rc = ext.main.__wrapped__ if hasattr(ext.main, "__wrapped__") else None
        # Simpler: invoke via subprocess-style argv simulation
        import subprocess

        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "extract_seeds_from_orchestrator.py"),
            "--orchestrator-seeds",
            str(orch_seeds),
            "--output",
            str(ROOT / "app" / "seeds"),
        ]
        subprocess.run(cmd, check=True)


async def _ensure_bundles_present() -> None:
    # Always rebuild bundles so they reflect the current seed JSON.
    import subprocess

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "build_bundles.py"),
        "--seeds",
        str(ROOT / "app" / "seeds"),
        "--output",
        str(ROOT / "app" / "bundles"),
        "--version",
        DEFAULT_VERSION,
    ]
    subprocess.run(cmd, check=True)


async def _upsert_attestation_key(session: AsyncSession) -> None:
    settings = get_settings()
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


async def _ensure_capabilities_recorded(session: AsyncSession) -> None:
    settings = get_settings()
    for capability in sorted(settings.capabilities):
        existing = (
            await session.execute(select(Capability).where(Capability.name == capability))
        ).scalar_one_or_none()
        if existing is None:
            session.add(Capability(name=capability, is_enabled=True))


async def _seed_static_token(session: AsyncSession) -> None:
    """Provision an opaque dev token if STATIC_TOKENS is empty."""
    settings = get_settings()
    if settings.static_tokens:
        return
    handle = "dev-token"
    digest = hash_token("tesslate-dev-token")
    existing = (
        await session.execute(select(ApiToken).where(ApiToken.handle == handle))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            ApiToken(
                handle=handle,
                token_hash=digest,
                scopes=[
                    "publish",
                    "submissions.read",
                    "yanks.write",
                    "yanks.appeal",
                    "reviews.write",
                    "telemetry.write",
                ],
            )
        )
        logger.info("seeded dev API token (raw value: tesslate-dev-token)")


async def _seed_categories(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, str]] = set()
    seeded = 0
    for entry in items:
        kind = entry["kind"]
        cat = entry.get("category")
        if not cat:
            continue
        key = (kind, cat)
        if key in seen:
            continue
        seen.add(key)
        existing = (
            await session.execute(select(Category).where(Category.kind == kind, Category.slug == cat))
        ).scalar_one_or_none()
        if existing is None:
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


async def _seed_one(session: AsyncSession, entry: dict[str, Any]) -> tuple[Item, ItemVersion, Bundle | None, bool]:
    kind = entry["kind"]
    slug = entry["slug"]
    version = entry.get("version") or DEFAULT_VERSION

    pricing_type = entry.get("pricing_type", "free")
    price_cents = int(entry.get("price", 0)) * 100 if isinstance(entry.get("price"), (int, float)) else 0
    pricing_payload = {
        "pricing_type": pricing_type,
        "price_cents": price_cents,
        "currency": "usd",
        "stripe_price_id": entry.get("stripe_price_id"),
    }

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
            select(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version == version)
        )
    ).scalar_one_or_none()
    if iv is None:
        iv = ItemVersion(
            item_id=item.id,
            version=version,
            changelog="Initial seed",
            manifest=entry,
        )
        session.add(iv)
        await session.flush()
    else:
        iv.manifest = entry

    item.latest_version = version
    item.latest_version_id = iv.id

    bundle: Bundle | None = None
    bundle_path = _bundle_path(kind, slug, version)
    if bundle_path.exists():
        bundle_bytes = bundle_path.read_bytes()
        sha = hashlib.sha256(bundle_bytes).hexdigest()
        # Persist via the storage adapter so the storage_key matches the live URL flow.
        storage = get_bundle_storage(get_settings())
        ref = storage.put_bytes(kind, slug, version, bundle_bytes)
        attestor = get_attestor(get_settings())
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
        else:
            existing_bundle.sha256 = ref.sha256
            existing_bundle.size_bytes = ref.size_bytes
            existing_bundle.storage_backend = ref.backend
            existing_bundle.storage_key = ref.storage_key
            existing_bundle.attestation_signature = attestation.signature
            existing_bundle.attestation_key_id = attestation.key_id
            existing_bundle.attestation_algorithm = attestation.algorithm
            bundle = existing_bundle

    return item, iv, bundle, created


async def _seed_featured(session: AsyncSession, entries: list[dict[str, Any]]) -> int:
    rank = 100
    seeded = 0
    for entry in entries:
        if not entry.get("is_featured"):
            continue
        item = (
            await session.execute(
                select(Item).where(Item.kind == entry["kind"], Item.slug == entry["slug"])
            )
        ).scalar_one_or_none()
        if item is None:
            continue
        existing = (
            await session.execute(
                select(FeaturedListing).where(FeaturedListing.kind == item.kind, FeaturedListing.item_id == item.id)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(FeaturedListing(kind=item.kind, item_id=item.id, rank=rank))
            seeded += 1
        rank += 10
    return seeded


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = get_settings()
    logger.info("init_db starting — DATABASE_URL=%s", settings.database_url.split("@")[-1])

    await create_all()
    await _ensure_seeds_present()
    await _ensure_bundles_present()

    factory = get_session_factory()
    all_entries: list[dict[str, Any]] = []
    for filename in SEED_FILES:
        path = _seed_path(filename)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("could not parse %s; skipping", path)
            continue
        if isinstance(data, list):
            all_entries.extend(data)

    logger.info("loading %d seed entries", len(all_entries))

    async with factory() as session:
        await _upsert_attestation_key(session)
        await _ensure_capabilities_recorded(session)
        await _seed_static_token(session)
        cat_count = await _seed_categories(session, all_entries)
        await session.commit()
        logger.info("seeded %d categories", cat_count)

    async with factory() as session:
        # Always emit a baseline 'startup' upsert so the changes feed has a tip
        # even when seeds are unchanged on a re-run.
        startup_event = await changes_emitter.emit(
            session,
            op="upsert",
            kind="agent",
            slug="__startup__",
            payload={"reason": "init_db boot tick", "timestamp": datetime.now(timezone.utc).isoformat()},
        )

        items_created = 0
        items_updated = 0
        for entry in all_entries:
            try:
                item, iv, _, created = await _seed_one(session, entry)
            except Exception:  # noqa: BLE001 - log and continue per-row
                logger.exception("failed to seed %s/%s", entry.get("kind"), entry.get("slug"))
                continue
            if created:
                items_created += 1
            else:
                items_updated += 1
            await changes_emitter.emit(
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

        featured_count = await _seed_featured(session, all_entries)
        await session.commit()
        logger.info(
            "items: %d created, %d updated; featured listings: %d; first etag: %s",
            items_created,
            items_updated,
            featured_count,
            startup_event.etag,
        )
    logger.info("init_db complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
