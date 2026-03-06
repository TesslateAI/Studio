"""
Add avatar_url column to marketplace_agents table

This migration adds the avatar_url column to store agent logo/profile pictures.

Run with:
    python scripts/migrations/add_avatar_url_column.py
"""

import asyncio
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from sqlalchemy import text
from app.database import engine
from app.config import get_settings

settings = get_settings()


async def add_avatar_url_column():
    """Add avatar_url column to marketplace_agents table."""

    print("🔄 Adding avatar_url column to marketplace_agents table...")

    async with engine.begin() as conn:
        # Check if column already exists
        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'marketplace_agents'
            AND column_name = 'avatar_url'
        """))

        if result.fetchone():
            print("✅ Column avatar_url already exists, skipping migration.")
            return

        # Add the column
        await conn.execute(text("""
            ALTER TABLE marketplace_agents
            ADD COLUMN avatar_url VARCHAR
        """))

        print("✅ Successfully added avatar_url column!")
        print("📝 Users can now upload custom logos for their agents.")


async def main():
    """Run the migration."""
    try:
        await add_avatar_url_column()
        print("\n✨ Migration completed successfully!")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
