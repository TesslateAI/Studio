"""
Migration: Add usage_count field to marketplace_agents table
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
from orchestrator.app.database import AsyncSessionLocal


async def migrate():
    """Add usage_count field to marketplace_agents table."""
    async with AsyncSessionLocal() as db:
        try:
            # Add usage_count column
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS usage_count INTEGER DEFAULT 0
            """))

            await db.commit()
            print("✅ Successfully added usage_count field to marketplace_agents")

        except Exception as e:
            print(f"❌ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
