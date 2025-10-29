"""
Migration: Add architecture_diagram and settings fields to projects table

This adds support for storing generated diagrams and project settings.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
from orchestrator.app.database import AsyncSessionLocal


async def migrate():
    """Add architecture_diagram and settings fields to projects table."""
    async with AsyncSessionLocal() as db:
        try:
            # Add architecture_diagram column
            await db.execute(text("""
                ALTER TABLE projects
                ADD COLUMN IF NOT EXISTS architecture_diagram TEXT NULL
            """))

            # Add settings column
            await db.execute(text("""
                ALTER TABLE projects
                ADD COLUMN IF NOT EXISTS settings JSON NULL
            """))

            await db.commit()
            print("✅ Successfully added architecture_diagram and settings fields to projects table")

        except Exception as e:
            print(f"❌ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
