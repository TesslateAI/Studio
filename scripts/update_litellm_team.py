#!/usr/bin/env python3
"""
Update LiteLLM user keys to use "internal" team/access group.

This allows users to access cerebras/qwen-3-coder-480b which requires
the "internal" access group in LiteLLM config.

Usage:
    python update_litellm_team.py
"""

import asyncio
import sys
import os

# Add the orchestrator app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator', 'app'))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import User
from app.services.litellm_service import litellm_service
from app.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def update_user_teams():
    """Update team/access group for all users with LiteLLM keys."""

    settings = get_settings()

    # Create database connection
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get all users with LiteLLM keys
        result = await session.execute(
            select(User).where(User.litellm_api_key != None)
        )
        users_with_keys = result.scalars().all()

        if not users_with_keys:
            logger.info("No users with LiteLLM API keys found!")
            return

        logger.info(f"Found {len(users_with_keys)} users with LiteLLM keys")

        # Update each user's key to "internal" team
        success_count = 0
        fail_count = 0

        for user in users_with_keys:
            try:
                logger.info(f"Updating team for user: {user.username} (ID: {user.id})")

                # Update the key's team/access group and models
                result = await litellm_service.update_user_team(
                    api_key=user.litellm_api_key,
                    team_id="internal",
                    models=["cerebras/qwen-3-coder-480b"]
                )

                if result:
                    logger.info(f"✅ Updated team to 'internal' for user {user.username}")
                    success_count += 1
                else:
                    logger.error(f"❌ Failed to update team for user {user.username}")
                    fail_count += 1

            except Exception as e:
                logger.error(f"❌ Error updating team for user {user.username}: {e}")
                fail_count += 1

        logger.info(f"\nMigration completed!")
        logger.info(f"Success: {success_count}, Failed: {fail_count}")


if __name__ == "__main__":
    asyncio.run(update_user_teams())
