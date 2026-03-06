"""
Script to create LiteLLM API keys for users who don't have them.
Run this inside the orchestrator container or with proper database access.
"""
import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'orchestrator'))

from app.database import AsyncSessionLocal
from app.models import User
from app.services.litellm_service import litellm_service
from sqlalchemy import select


async def fix_user_keys():
    """Create LiteLLM keys for all users who don't have them."""
    async with AsyncSessionLocal() as db:
        # Get all users without LiteLLM keys
        result = await db.execute(
            select(User).where(User.litellm_api_key == None)
        )
        users_without_keys = result.scalars().all()

        if not users_without_keys:
            print("✅ All users already have LiteLLM API keys!")
            return

        print(f"Found {len(users_without_keys)} users without LiteLLM keys:\n")

        for user in users_without_keys:
            print(f"Creating key for user: {user.username} (ID: {user.id})")

            try:
                # Create LiteLLM key
                litellm_result = await litellm_service.create_user_key(
                    user_id=user.id,
                    username=user.username
                )

                # Update user with LiteLLM details
                user.litellm_api_key = litellm_result["api_key"]
                user.litellm_user_id = litellm_result["litellm_user_id"]
                await db.commit()

                print(f"  ✅ Created key for {user.username}")
                print(f"     Key: {litellm_result['api_key'][:20]}...")
                print(f"     Models: {litellm_result['models']}")
                print(f"     Budget: ${litellm_result['budget']}\n")

            except Exception as e:
                print(f"  ❌ Failed to create key for {user.username}: {e}\n")
                await db.rollback()

        print("Done!")


if __name__ == "__main__":
    asyncio.run(fix_user_keys())