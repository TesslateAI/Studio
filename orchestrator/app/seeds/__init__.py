"""
Database seed scripts for initial data population.

All seed functions are idempotent and safe to run on every startup.
"""

import logging

from .community_bases import seed_community_bases
from .deployment_targets import seed_deployment_targets
from .marketplace_agents import (
    auto_add_agent_builder_to_users,
    auto_add_librarian_agent_to_users,
    auto_add_tesslate_agent_to_users,
    get_or_create_tesslate_account,
    seed_marketplace_agents,
)
from .marketplace_bases import seed_marketplace_bases
from .mcp_servers import seed_mcp_servers
from .opensource_agents import seed_opensource_agents
from .skills import seed_skills
from .themes import seed_themes
from .workflow_templates import WORKFLOW_TEMPLATES, seed_workflow_templates

logger = logging.getLogger(__name__)

__all__ = [
    "run_all_seeds",
    "seed_marketplace_bases",
    "seed_community_bases",
    "seed_marketplace_agents",
    "seed_mcp_servers",
    "seed_opensource_agents",
    "seed_skills",
    "seed_themes",
    "seed_workflow_templates",
    "seed_deployment_targets",
    "auto_add_tesslate_agent_to_users",
    "auto_add_librarian_agent_to_users",
    "auto_add_agent_builder_to_users",
    "get_or_create_tesslate_account",
    "WORKFLOW_TEMPLATES",
]


async def run_all_seeds():
    """Run all seeds in dependency order. Idempotent, safe for every startup.

    Each seed is wrapped in try/except so one failure doesn't block the rest.
    Runs in a single session for efficiency.
    """
    from ..database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # 1. Marketplace bases (no dependencies)
        try:
            count = await seed_marketplace_bases(db)
            logger.info("Seed marketplace bases: %d new", count)
        except Exception:
            logger.exception("Failed to seed marketplace bases")
            await db.rollback()

        # 1.5. Community bases (creates community account)
        try:
            count = await seed_community_bases(db)
            logger.info("Seed community bases: %d new", count)
        except Exception:
            logger.exception("Failed to seed community bases")
            await db.rollback()

        # 2. Official agents (creates Tesslate account)
        try:
            count = await seed_marketplace_agents(db)
            logger.info("Seed marketplace agents: %d new", count)
        except Exception:
            logger.exception("Failed to seed marketplace agents")
            await db.rollback()

        # 3. Open-source agents (reuses Tesslate account)
        try:
            count = await seed_opensource_agents(db)
            logger.info("Seed open-source agents: %d new", count)
        except Exception:
            logger.exception("Failed to seed open-source agents")
            await db.rollback()

        # 4. Auto-add Tesslate Agent to all users
        try:
            count = await auto_add_tesslate_agent_to_users(db)
            logger.info("Auto-add Tesslate Agent: %d users updated", count)
        except Exception:
            logger.exception("Failed to auto-add Tesslate Agent to users")
            await db.rollback()

        # 4b. Auto-add Librarian agent to all users
        try:
            count = await auto_add_librarian_agent_to_users(db)
            logger.info("Auto-add Librarian agent: %d users updated", count)
        except Exception:
            logger.exception("Failed to auto-add Librarian agent to users")
            await db.rollback()

        # 4c. Auto-add Agent Builder to all users
        try:
            count = await auto_add_agent_builder_to_users(db)
            logger.info("Auto-add Agent Builder: %d users updated", count)
        except Exception:
            logger.exception("Failed to auto-add Agent Builder to users")
            await db.rollback()

        # 5. Skills (item_type='skill')
        try:
            count = await seed_skills(db)
            logger.info("Seed skills: %d new", count)
        except Exception:
            logger.exception("Failed to seed skills")
            await db.rollback()

        # 6. MCP servers / connectors (item_type='mcp_server')
        try:
            count = await seed_mcp_servers(db)
            logger.info("Seed MCP servers: %d new", count)
        except Exception:
            logger.exception("Failed to seed MCP servers")
            await db.rollback()

        # 7. Themes
        try:
            count = await seed_themes(db)
            logger.info("Seed themes: %d processed", count)
        except Exception:
            logger.exception("Failed to seed themes")
            await db.rollback()

        # 8. Workflow templates
        try:
            count = await seed_workflow_templates(db)
            logger.info("Seed workflow templates: %d new", count)
        except Exception:
            logger.exception("Failed to seed workflow templates")
            await db.rollback()

        # 9. Deployment targets (item_type='deployment_target')
        try:
            count = await seed_deployment_targets(db)
            logger.info("Seed deployment targets: %d new", count)
        except Exception:
            logger.exception("Failed to seed deployment targets")
            await db.rollback()

    logger.info("All database seeds completed")
