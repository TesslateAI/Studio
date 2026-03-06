"""
Create LiteLLM key directly without user creation step.
"""
import asyncio
import aiohttp
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'orchestrator'))

from app.database import AsyncSessionLocal
from app.models import User
from app.config import get_settings
from sqlalchemy import select

settings = get_settings()


async def create_key_direct(username: str):
    """Create LiteLLM key directly (skip user creation)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ User '{username}' not found!")
            return

        print(f"User: {user.username} (ID: {user.id})")

        litellm_user_id = f"user_{user.id}_{user.username}"

        # Try calling /key/generate directly
        key_data = {
            "user_id": litellm_user_id,
            "user_email": f"{user.username}@{settings.litellm_email_domain}",
            "key_alias": f"{user.username}_key",
            "models": settings.litellm_default_models.split(","),
            "team_id": settings.litellm_team_id,
            "max_budget": settings.litellm_initial_budget,
            "duration": "365d",
            "metadata": {
                "tesslate_user_id": user.id,
                "username": user.username
            }
        }

        headers = {
            "Authorization": f"Bearer {settings.litellm_master_key}",
            "Content-Type": "application/json"
        }

        print(f"\nCalling {settings.litellm_api_base}/key/generate...")
        print(f"Data: {key_data}")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{settings.litellm_api_base}/key/generate",
                    headers=headers,
                    json=key_data
                ) as resp:
                    print(f"Status: {resp.status}")
                    response_text = await resp.text()
                    print(f"Response: {response_text[:500]}")

                    if resp.status == 200:
                        key_response = await resp.json()

                        # Update user
                        user.litellm_api_key = key_response.get("key")
                        user.litellm_user_id = litellm_user_id
                        await db.commit()

                        print(f"\n✅ Successfully created key!")
                        print(f"   Key: {key_response.get('key', '')[:20]}...")
                        print(f"   User ID: {litellm_user_id}")
                    else:
                        print(f"\n❌ Failed with status {resp.status}")

            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "a"
    asyncio.run(create_key_direct(username))
