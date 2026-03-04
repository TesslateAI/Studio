"""
Regenerate all user LiteLLM keys to remove model restrictions.

This script regenerates keys for all users to allow access to all team models
instead of being restricted to specific models.

Run with: python scripts/regenerate_user_keys.py
"""

import asyncio
import sys
import os

# Add parent directory to path to import from orchestrator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import select
from orchestrator.app.database import AsyncSessionLocal
from orchestrator.app.models import User
from orchestrator.app.services.litellm_service import LiteLLMService


async def regenerate_keys():
    """Regenerate LiteLLM keys for all users."""
    litellm_service = LiteLLMService()

    async with AsyncSessionLocal() as db:
        # Get all users
        result = await db.execute(select(User))
        users = result.scalars().all()

        print(f"Found {len(users)} users")

        for user in users:
            try:
                print(f"\n{'='*60}")
                print(f"Processing user: {user.username} (ID: {user.id})")

                if user.litellm_api_key:
                    print(f"  Current key: {user.litellm_api_key[:20]}...")
                    print(f"  Revoking old key...")

                    # Try to revoke old key (may fail if already invalid)
                    try:
                        await litellm_service.revoke_key(user.litellm_api_key)
                        print(f"  ✓ Old key revoked")
                    except Exception as e:
                        print(f"  ⚠ Could not revoke old key (may already be invalid): {e}")

                # Create new key WITHOUT model restrictions
                print(f"  Creating new key without model restrictions...")
                litellm_result = await litellm_service.create_user_key(
                    user_id=user.id,
                    username=user.username
                    # Note: NOT passing models parameter - will inherit from team
                )

                # Update user with new key
                user.litellm_api_key = litellm_result["api_key"]
                user.litellm_user_id = litellm_result["litellm_user_id"]
                await db.commit()

                print(f"  ✓ New key created: {user.litellm_api_key[:20]}...")
                print(f"  ✓ Models: {litellm_result['models']}")
                print(f"  ✓ Budget: ${litellm_result['budget']}")

            except Exception as e:
                print(f"  ✗ Error processing user {user.username}: {e}")
                await db.rollback()
                continue

        print(f"\n{'='*60}")
        print("✅ Key regeneration completed!")
        print("\nAll users can now access all internal team models.")


if __name__ == "__main__":
    print("Regenerating LiteLLM keys for all users...")
    print("This will revoke old keys and create new ones without model restrictions.\n")

    response = input("Continue? (yes/no): ")
    if response.lower() != "yes":
        print("Aborted.")
        sys.exit(0)

    asyncio.run(regenerate_keys())
