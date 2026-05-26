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
  * ``seed_system_default_agent`` — the pseudo-row backing the
    code-resident system default agent. Identity + config live in
    ``services.default_agent``; this seed plants (and re-asserts on
    every boot) the single ``marketplace_agents`` row so FKs from
    ``user_purchased_agents`` etc. resolve. Replaces the old per-user
    ``auto_add_tesslate_agent_to_users`` sweep — the default is now
    derived in the listing endpoint, not stored per-user.
  * Library auto-add backfill for *helper* canonical agents (Librarian,
    Agent Builder, Automation Builder, Service Integrator). These are
    separate from the system default; they remain real marketplace
    items every user gets nudged toward. The actual logic lives in
    ``services.library_seeder``.

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
    from ..services.default_agent import seed_system_default_agent
    from ..services.library_seeder import (
        CANONICAL_AGENTS,
        add_agent_to_users_by_slug,
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

        # 2. System default agent pseudo-row. Identity + config live in
        # services.default_agent; this is the single FK target backing
        # the code-resident default. Rewrites the row's columns from
        # SYSTEM_DEFAULT_AGENT_FIELDS on every boot — code is the source
        # of truth, the DB row is a referential anchor.
        try:
            await seed_system_default_agent(db)
        except Exception:
            logger.exception("Failed to seed system default agent")
            await db.rollback()

        # 3. Library auto-add for the *other* canonical helper agents
        # (Librarian, Agent Builder, Automation Builder, Service
        # Integrator). The system default is NOT in this loop — it's
        # implicit in the /my-agents listing and never written to
        # user_purchased_agents at signup. These helpers are still real
        # marketplace items every user gets nudged toward; the rows
        # themselves come from federation sync, so on a truly fresh
        # deploy these may no-op until the first sync poll lands.
        for slug, label in CANONICAL_AGENTS:
            try:
                count = await add_agent_to_users_by_slug(db, slug=slug, display_name=label)
                logger.info("Auto-add %s: %d users updated", label, count)
            except Exception:
                logger.exception("Failed to auto-add %s to users", label)
                await db.rollback()

    logger.info("All database seeds completed")
