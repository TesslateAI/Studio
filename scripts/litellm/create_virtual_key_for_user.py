"""
Script to create a proper LiteLLM virtual key for a specific user.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'orchestrator'))

from app.database import AsyncSessionLocal
from app.models import User
from app.services.litellm_service import litellm_service
from sqlalchemy import select


async def create_key_for_user(username: str):
    """Create a proper LiteLLM virtual key for the specified user."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ User '{username}' not found!")
            return

        print(f"User: {user.username} (ID: {user.id})")
        if user.litellm_api_key:
            print(f"Current key: {user.litellm_api_key[:20]}...")
            print("Removing current key and creating new virtual key...")
            user.litellm_api_key = None
            user.litellm_user_id = None
            await db.commit()

        print(f"\nCreating proper virtual key for {user.username}...")
        try:
            litellm_result = await litellm_service.create_user_key(
                user_id=user.id,
                username=user.username
            )

            user.litellm_api_key = litellm_result["api_key"]
            user.litellm_user_id = litellm_result["litellm_user_id"]
            await db.commit()

            print(f"\n✅ Successfully created virtual key!")
            print(f"   Key: {litellm_result['api_key'][:20]}...")
            print(f"   User ID: {litellm_result['litellm_user_id']}")
            print(f"   Models: {litellm_result['models']}")
            print(f"   Budget: ${litellm_result['budget']}")

        except Exception as e:
            print(f"\n❌ Failed to create virtual key: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "a"
    asyncio.run(create_key_for_user(username))
