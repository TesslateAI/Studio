"""
Migration: Add diagram_model field to users table

This adds support for user-selected models for architecture diagram generation.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
from orchestrator.app.database import AsyncSessionLocal


async def migrate():
    """Add diagram_model field to users table."""
    async with AsyncSessionLocal() as db:
        try:
            # Add diagram_model column
            await db.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS diagram_model VARCHAR NULL
            """))

            await db.commit()
            print("✅ Successfully added diagram_model field to users table")

        except Exception as e:
            print(f"❌ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
