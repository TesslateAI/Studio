#!/usr/bin/env python3
"""
Migration script to generate LiteLLM API keys for existing users.

This script should be run once after deploying the per-user LiteLLM key feature.
It will create API keys for all users who don't have one yet.

Usage:
    python migrate_litellm_keys.py
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import User
from app.services.litellm_service import litellm_service
from app.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_users():
    """Generate LiteLLM keys for all users without them."""

    settings = get_settings()

    # Create database connection
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get all users without LiteLLM keys
        result = await session.execute(
            select(User).where(User.litellm_api_key == None)
        )
        users_without_keys = result.scalars().all()

        if not users_without_keys:
            logger.info("All users already have LiteLLM API keys!")
            return

        logger.info(f"Found {len(users_without_keys)} users without LiteLLM keys")

        # Generate keys for each user
        for user in users_without_keys:
            try:
                logger.info(f"Generating LiteLLM key for user: {user.username} (ID: {user.id})")

                # Create LiteLLM key
                litellm_result = await litellm_service.create_user_key(
                    user_id=user.id,
                    username=user.username
                )

                # Update user with LiteLLM details
                user.litellm_api_key = litellm_result["api_key"]
                user.litellm_user_id = litellm_result["litellm_user_id"]

                logger.info(f"✅ Created LiteLLM key for user {user.username}")

            except Exception as e:
                logger.error(f"❌ Failed to create LiteLLM key for user {user.username}: {e}")
                # Continue with other users

        # Commit all changes
        await session.commit()
        logger.info("Migration completed!")


if __name__ == "__main__":
    asyncio.run(migrate_users())
