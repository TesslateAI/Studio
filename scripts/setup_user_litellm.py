#!/usr/bin/env python3
"""
Add users to the internal team and update their keys.

This script:
1. Adds each user to the "internal" team in LiteLLM
2. Updates their API key to access cerebras/qwen-3-coder-480b

Usage:
    python setup_user_litellm.py
"""

import asyncio
import aiohttp
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


async def add_user_to_team(litellm_user_id: str, settings):
    """Add a user to the internal team."""
    base_url = settings.litellm_api_base.replace('/v1', '')
    master_key = settings.litellm_master_key

    headers = {
        "Authorization": f"Bearer {master_key}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            # Add user to internal team
            member_data = {
                "team_id": "internal",
                "member": {
                    "user_id": litellm_user_id,
                    "role": "user"
                }
            }

            async with session.post(
                f"{base_url}/team/member_add",
                headers=headers,
                json=member_data
            ) as resp:
                if resp.status == 200:
                    logger.info(f"✅ Added {litellm_user_id} to internal team")
                    return True
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Failed to add user to team: {error_text}")
                    return False

        except Exception as e:
            logger.error(f"❌ Error adding user to team: {e}")
            return False


async def setup_users():
    """Setup all users in LiteLLM."""

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

        success_count = 0
        fail_count = 0

        for user in users_with_keys:
            try:
                logger.info(f"\nProcessing user: {user.username} (ID: {user.id})")

                # Step 1: Add user to internal team
                added = await add_user_to_team(user.litellm_user_id, settings)

                if not added:
                    logger.warning(f"⚠️ Couldn't add user to team, but will try updating key anyway")

                # Step 2: Update key to access cerebras model
                result = await litellm_service.update_user_team(
                    api_key=user.litellm_api_key,
                    team_id="internal",
                    models=["cerebras/qwen-3-coder-480b"]
                )

                if result:
                    logger.info(f"✅ Successfully configured user {user.username}")
                    success_count += 1
                else:
                    logger.error(f"❌ Failed to update key for user {user.username}")
                    fail_count += 1

            except Exception as e:
                logger.error(f"❌ Error processing user {user.username}: {e}")
                fail_count += 1

        logger.info(f"\n{'='*60}")
        logger.info(f"Setup completed!")
        logger.info(f"Success: {success_count}, Failed: {fail_count}")
        logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(setup_users())
