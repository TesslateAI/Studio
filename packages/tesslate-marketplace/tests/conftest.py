"""
Shared pytest fixtures.

Each test session points the marketplace at a fresh SQLite database under a
temp directory so the test runs are deterministic and don't depend on a live
Postgres instance.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

# Add project root to sys.path so `app` and `client.python` import cleanly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "client" / "python"))


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture()
async def env(tmp_path, monkeypatch):
    """Per-test environment with fresh SQLite + temp bundle storage + key files."""
    db_file = tmp_path / "marketplace.db"
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    hub_id_file = tmp_path / ".hub_id"
    attestation_file = tmp_path / ".attestation_key"

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("BUNDLE_STORAGE_DIR", str(bundles))
    monkeypatch.setenv("BUNDLE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("BUNDLE_BASE_URL", "http://testserver")
    monkeypatch.setenv("HUB_ID_FILE", str(hub_id_file))
    monkeypatch.setenv("HUB_DISPLAY_NAME", "Tesslate Test Hub")
    monkeypatch.setenv("ATTESTATION_KEY_PATH", str(attestation_file))
    monkeypatch.setenv("OPENSAIL_ENV", "test")
    monkeypatch.setenv("STATIC_TOKENS", "test-token:publish:submissions.read:yanks.write:yanks.appeal:reviews.write:telemetry.write")
    monkeypatch.delenv("DISABLED_CAPABILITIES", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("HUB_ID", raising=False)

    # Force singleton resets so the new env wins.
    from app.config import reload_settings
    from app.database import reset_engine
    from app.services.attestations import reset_attestor_cache
    from app.services.cas import reset_bundle_storage_cache
    from app.services.hub_id import reset_hub_id_cache

    reload_settings()
    await reset_engine()
    reset_hub_id_cache()
    reset_attestor_cache()
    reset_bundle_storage_cache()

    from app.database import create_all

    await create_all()
    yield {"tmp_path": tmp_path, "bundles": bundles}

    await reset_engine()


@pytest_asyncio.fixture()
async def client(env) -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture()
async def seeded(env, client):
    """Insert a small but realistic catalog so list/detail tests have data."""
    from app.database import session_scope
    from app.models import (
        AttestationKey,
        Bundle,
        Category,
        FeaturedListing,
        Item,
        ItemVersion,
        Review,
        ReviewAggregate,
    )
    from app.services import changes_emitter
    from app.services.attestations import get_attestor
    from app.services.cas import get_bundle_storage
    from app.services.install_check import write_tar_zst

    storage = get_bundle_storage()
    attestor = get_attestor()

    items = [
        {
            "kind": "agent",
            "slug": "tesslate-agent",
            "name": "Tesslate Agent",
            "description": "Official autonomous coding agent",
            "category": "fullstack",
            "tags": ["coder", "agent"],
            "is_featured": True,
            "version": "0.1.0",
            "pricing_type": "free",
            "price_cents": 0,
        },
        {
            "kind": "agent",
            "slug": "agent-builder",
            "name": "Agent Builder",
            "description": "Drafts new agents",
            "category": "tooling",
            "tags": ["meta"],
            "version": "0.1.0",
        },
        {
            "kind": "skill",
            "slug": "react-best-practices",
            "name": "React Best Practices",
            "description": "Performance patterns",
            "category": "frontend",
            "version": "0.1.0",
        },
        {
            "kind": "base",
            "slug": "nextjs-16",
            "name": "Next.js 16",
            "description": "App Router base",
            "category": "fullstack",
            "version": "0.1.0",
        },
        {
            "kind": "theme",
            "slug": "midnight",
            "name": "Midnight",
            "description": "Deep indigo theme",
            "category": "minimal",
            "is_featured": True,
            "version": "0.1.0",
        },
        {
            "kind": "agent",
            "slug": "paid-agent",
            "name": "Paid Agent",
            "description": "Costs money",
            "category": "premium",
            "version": "0.1.0",
            "pricing_type": "paid",
            "price_cents": 1500,
        },
    ]

    from sqlalchemy import select

    async with session_scope() as session:
        # Register attestation key once (lifespan would do this in a real boot).
        existing_key = (
            await session.execute(
                select(AttestationKey).where(AttestationKey.key_id == attestor.public_key_id())
            )
        ).scalar_one_or_none()
        if existing_key is None:
            session.add(
                AttestationKey(
                    key_id=attestor.public_key_id(),
                    public_key_pem=attestor.public_key_pem(),
                    is_active=True,
                )
            )

        for entry in items:
            item = Item(
                kind=entry["kind"],
                slug=entry["slug"],
                name=entry["name"],
                description=entry["description"],
                category=entry["category"],
                tags=entry.get("tags", []),
                is_featured=entry.get("is_featured", False),
                pricing_type=entry.get("pricing_type", "free"),
                price_cents=entry.get("price_cents", 0),
                pricing_payload={
                    "pricing_type": entry.get("pricing_type", "free"),
                    "price_cents": entry.get("price_cents", 0),
                    "currency": "usd",
                },
                latest_version=entry["version"],
            )
            session.add(item)
            await session.flush()
            iv = ItemVersion(
                item_id=item.id,
                version=entry["version"],
                manifest={"slug": entry["slug"], "name": entry["name"]},
            )
            session.add(iv)
            await session.flush()
            item.latest_version_id = iv.id

            # Build a tiny valid bundle and put it through the CAS adapter.
            data = write_tar_zst(
                {
                    "item.manifest.json": json.dumps(entry, sort_keys=True).encode("utf-8"),
                }
            )
            ref = storage.put_bytes(item.kind, item.slug, iv.version, data)
            attestation = attestor.sign_sha256(ref.sha256)
            session.add(
                Bundle(
                    item_version_id=iv.id,
                    sha256=ref.sha256,
                    size_bytes=ref.size_bytes,
                    storage_backend=ref.backend,
                    storage_key=ref.storage_key,
                    attestation_signature=attestation.signature,
                    attestation_key_id=attestation.key_id,
                    attestation_algorithm=attestation.algorithm,
                )
            )

            await changes_emitter.emit(
                session,
                op="upsert",
                kind=item.kind,
                slug=item.slug,
                version=iv.version,
                payload={"name": item.name, "category": item.category},
            )

            # Categories — Category PK is `id`, so use a (kind, slug) lookup.
            row = (
                await session.execute(
                    select(Category).where(Category.kind == item.kind, Category.slug == item.category)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    Category(
                        kind=item.kind,
                        slug=item.category,
                        name=item.category.replace("-", " ").title(),
                    )
                )

            if entry.get("is_featured"):
                session.add(FeaturedListing(kind=item.kind, item_id=item.id, rank=100))

            # Drop a single review for the tesslate-agent so review tests have data.
            if entry["slug"] == "tesslate-agent":
                review = Review(
                    item_id=item.id,
                    rating=5,
                    title="Solid",
                    body="Worked first try",
                    reviewer_handle="user-a",
                )
                session.add(review)
                await session.flush()
                session.add(
                    ReviewAggregate(
                        item_id=item.id,
                        count=1,
                        mean=5.0,
                        distribution={"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
                    )
                )
                item.rating = 5.0
                item.reviews_count = 1

    return items


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}
