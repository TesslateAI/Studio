"""Seed the two immutable system marketplace sources.

This seed is the safety net for the federated-marketplace source registry.
The alembic migration ``0088_marketplace_sources`` creates the rows on first
upgrade with deterministic UUIDs; this seed runs on every boot and:

  - reasserts existence (idempotent UPSERT by handle) for environments
    that bypassed migrations or restored from a partial backup;
  - refreshes mutable fields (display_name, base_url) so a redeploy can
    update branding/URLs without a migration;
  - never modifies trust_level, scope, or pinned_hub_id — those are
    structural and would change federation semantics.

Cloud-mode user/team scoped Local sources are NOT seeded here; they are
created lazily on first draft save by the marketplace_sources router
(Wave 5). This file only owns the two system rows.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketplaceSource

logger = logging.getLogger(__name__)

# Must match the constants used by alembic 0088_marketplace_sources.
TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LOCAL_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

SYSTEM_SOURCES = [
    {
        "id": TESSLATE_OFFICIAL_ID,
        "handle": "tesslate-official",
        "display_name": "Tesslate Official",
        "base_url": "https://marketplace.tesslate.com",
        "scope": "system",
        "trust_level": "official",
    },
    {
        "id": LOCAL_SOURCE_ID,
        "handle": "local",
        "display_name": "Local",
        "base_url": "local://filesystem",
        "scope": "system",
        "trust_level": "local",
    },
]


async def seed_marketplace_sources(db: AsyncSession) -> int:
    """Idempotent UPSERT of the two immutable system MarketplaceSource rows.

    Returns the number of newly created rows (0 on a healthy boot, 2 on a
    fresh install that somehow skipped migrations).
    """
    created = 0
    for spec in SYSTEM_SOURCES:
        result = await db.execute(
            select(MarketplaceSource).where(
                MarketplaceSource.handle == spec["handle"],
                MarketplaceSource.scope == "system",
            )
        )
        existing = result.scalars().first()

        if existing is None:
            row = MarketplaceSource(
                id=spec["id"],
                handle=spec["handle"],
                display_name=spec["display_name"],
                base_url=spec["base_url"],
                scope=spec["scope"],
                trust_level=spec["trust_level"],
                is_active=True,
            )
            db.add(row)
            created += 1
            logger.info("seed_marketplace_sources: created handle=%s", spec["handle"])
        else:
            # Refresh mutable fields only. trust_level/scope/id/handle are
            # structural and never overwritten.
            existing.display_name = spec["display_name"]
            existing.base_url = spec["base_url"]
            if not existing.is_active:
                existing.is_active = True

    # Commit either way: refreshed mutable fields on existing rows must
    # also be persisted, not just newly inserted rows.
    await db.commit()

    if created:
        logger.info("seed_marketplace_sources: created %d new system rows", created)

    return created
