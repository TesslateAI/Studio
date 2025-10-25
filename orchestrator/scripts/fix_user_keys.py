"""
Fix script to add LiteLLM API keys to users who don't have them.

This script finds all users without litellm_api_key and creates keys for them.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User
from app.services.litellm_service import litellm_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def fix_user_keys():
    """Add LiteLLM API keys to users who don't have them."""

    async with AsyncSessionLocal() as db:
        try:
            # Find all users without litellm_api_key
            result = await db.execute(
                select(User).where(
                    (User.litellm_api_key == None) | (User.litellm_api_key == '')
                )
            )
            users_without_keys = result.scalars().all()

            if not users_without_keys:
                logger.info("✅ All users already have LiteLLM API keys!")
                return

            logger.info(f"Found {len(users_without_keys)} users without LiteLLM API keys")

            for user in users_without_keys:
                try:
                    logger.info(f"Creating LiteLLM key for user: {user.username} (ID: {user.id})")

                    # Create LiteLLM key
                    litellm_result = await litellm_service.create_user_key(
                        user_id=user.id,
                        username=user.username
                    )

                    # Update user
                    user.litellm_api_key = litellm_result["api_key"]
                    user.litellm_user_id = litellm_result["litellm_user_id"]
                    await db.commit()

                    logger.info(f"✅ Created LiteLLM key for {user.username}")

                except Exception as e:
                    logger.error(f"❌ Failed to create key for {user.username}: {e}")
                    await db.rollback()
                    continue

            logger.info(f"✅ Finished! Processed {len(users_without_keys)} users")

        except Exception as e:
            logger.error(f"❌ Script failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(fix_user_keys())
