"""
Delete all marketplace agents and bases.

HOW TO RUN:
-----------
Docker:
  docker cp scripts/seed/delete_all_marketplace.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/delete_all_marketplace.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import sys
import os

# For Docker: Working directory is /app which contains the app/ module
if os.path.exists('/app/app'):
    sys.path.insert(0, '/app')
else:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings


async def delete_all():
    """Delete all marketplace agents and bases."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Deleting All Marketplace Data ===\n")

        # Delete in order of dependencies
        tables = [
            ("marketplace_transactions", "MarketplaceTransaction"),
            ("user_purchased_agents", "UserPurchasedAgent"),
            ("marketplace_agents", "MarketplaceAgent"),
            ("marketplace_bases", "MarketplaceBase"),
        ]

        for table_name, display_name in tables:
            try:
                result = await db.execute(text(f"DELETE FROM {table_name}"))
                count = result.rowcount
                print(f"✓ Deleted {count} rows from {display_name}")
            except Exception as e:
                print(f"⚠ Could not delete from {table_name}: {e}")

        await db.commit()
        print("\n=== Cleanup Complete ===\n")


if __name__ == "__main__":
    asyncio.run(delete_all())
