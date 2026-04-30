"""
Database seed scripts for initial data population.

After Wave 10 the orchestrator no longer carries any marketplace catalog
seeds. The federation sync worker (``services.marketplace_sync``) is the
sole population path for catalog rows on fresh deploys — it pulls items
from each registered ``MarketplaceSource`` and upserts them into the
local cache tables, tagging every row with ``source_id`` and
``source_etag``.

This module is intentionally narrow now. It owns only:

  * ``seed_marketplace_sources`` — the two immutable system rows
    (``Tesslate Official`` + ``Local``) that anchor every other catalog
    write. Mirrors the alembic 0088 migration so a DB restored from a
    partial backup or a fresh-table-creation environment still ends up
    with a valid source registry.
  * ``seed_deployment_targets`` — system-managed deployment provider
    catalog (``item_type='deployment_target'``). NOT a federated
    marketplace primitive; lives orchestrator-side because the deploy
    pipeline routes through it directly.
  * Library auto-add backfill — every user gets the canonical Tesslate
    agents in their library on every boot. The agents themselves come
    from federation sync; this code only manages the user-state
    ``UserPurchasedAgent`` rows. The actual logic lives in
    ``services.library_seeder`` and is called from here so the boot
    sequence stays observable in one place.

All seed functions are idempotent and safe to run on every startup. Each
call is wrapped in its own try/except so one failure doesn't cascade.
"""

import logging

from .deployment_targets import seed_deployment_targets
from .marketplace_sources import seed_marketplace_sources

logger = logging.getLogger(__name__)

__all__ = [
    "run_all_seeds",
    "seed_marketplace_sources",
    "seed_deployment_targets",
]


async def run_all_seeds():
    """Run the orchestrator's system-row seeds + library auto-add backfill.

    The catalog itself is owned by the marketplace service after Wave 10;
    this entry point is intentionally narrow.

    Idempotent — safe for every startup. Each step is wrapped in
    try/except so one failure doesn't block the rest.
    """
    from ..database import AsyncSessionLocal
    from ..services.library_seeder import (
        CANONICAL_AGENTS,
        add_agent_to_users_by_slug,
        auto_add_tesslate_agent_to_users,
    )

    async with AsyncSessionLocal() as db:
        # 0. Marketplace sources MUST seed first — every other row that
        # might land via federation sync carries source_id (NOT NULL FK to
        # marketplace_sources). The alembic migration creates the two
        # system rows on first upgrade; this seed is the safety net for
        # environments that bypassed migrations or restored from a
        # partial backup, and refreshes the mutable display_name/base_url
        # fields on every boot.
        try:
            count = await seed_marketplace_sources(db)
            logger.info("Seed marketplace sources: %d new", count)
        except Exception:
            logger.exception("Failed to seed marketplace sources")
            await db.rollback()

        # 1. Deployment targets (item_type='deployment_target'). Not part
        # of the federated catalog — system-managed provider list backing
        # the deploy router.
        try:
            count = await seed_deployment_targets(db)
            logger.info("Seed deployment targets: %d new", count)
        except Exception:
            logger.exception("Failed to seed deployment targets")
            await db.rollback()

        # 2. Library auto-add: ensure every user has the canonical
        # Tesslate agents in their library. These functions look up
        # MarketplaceAgent rows by slug — the rows themselves are
        # populated by the federation sync worker, so on a TRULY fresh
        # deploy these auto-adds may no-op until the first successful
        # sync poll lands. After that, every restart picks them up.
        # Order matters for the chat default-agent pick: Tesslate Agent
        # is added LAST so its purchase_date is the most recent.
        for slug, label in CANONICAL_AGENTS:
            try:
                count = await add_agent_to_users_by_slug(db, slug=slug, display_name=label)
                logger.info("Auto-add %s: %d users updated", label, count)
            except Exception:
                logger.exception("Failed to auto-add %s to users", label)
                await db.rollback()
        try:
            count = await auto_add_tesslate_agent_to_users(db)
            logger.info("Auto-add Tesslate Agent: %d users updated", count)
        except Exception:
            logger.exception("Failed to auto-add Tesslate Agent to users")
            await db.rollback()

    logger.info("All database seeds completed")
