#!/usr/bin/env python3
"""
Update LiteLLM user keys to allow access to cerebras/qwen-3-coder-480b model.

This script updates all existing user API keys to include the new default model.

Usage:
    python update_litellm_models.py
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


async def update_user_models():
    """Update model access for all users with LiteLLM keys."""

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

        # New model list (including the Cerebras model)
        new_models = ["cerebras/qwen-3-coder-480b"]

        # Update each user's key
        success_count = 0
        fail_count = 0

        for user in users_with_keys:
            try:
                logger.info(f"Updating models for user: {user.username} (ID: {user.id})")

                # Update the key's allowed models
                result = await litellm_service.update_user_models(
                    api_key=user.litellm_api_key,
                    models=new_models
                )

                if result:
                    logger.info(f"✅ Updated models for user {user.username}")
                    success_count += 1
                else:
                    logger.error(f"❌ Failed to update models for user {user.username}")
                    fail_count += 1

            except Exception as e:
                logger.error(f"❌ Error updating models for user {user.username}: {e}")
                fail_count += 1

        logger.info(f"\nMigration completed!")
        logger.info(f"Success: {success_count}, Failed: {fail_count}")


if __name__ == "__main__":
    asyncio.run(update_user_models())
