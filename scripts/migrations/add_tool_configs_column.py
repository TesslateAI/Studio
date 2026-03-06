"""
Add tool_configs column to marketplace_agents table

This migration adds the tool_configs JSON column to store custom
tool descriptions and examples for each agent.

Run with:
    python scripts/migrations/add_tool_configs_column.py
"""

import asyncio
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from sqlalchemy import text
from app.database import engine, AsyncSessionLocal
from app.config import get_settings

settings = get_settings()


async def add_tool_configs_column():
    """Add tool_configs column to marketplace_agents table."""

    print("🔄 Adding tool_configs column to marketplace_agents table...")

    async with engine.begin() as conn:
        # Check if column already exists
        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'marketplace_agents'
            AND column_name = 'tool_configs'
        """))

        if result.fetchone():
            print("✅ Column tool_configs already exists, skipping migration.")
            return

        # Add the column
        await conn.execute(text("""
            ALTER TABLE marketplace_agents
            ADD COLUMN tool_configs JSON
        """))

        print("✅ Successfully added tool_configs column!")
        print("📝 You can now customize tool descriptions and examples for each agent.")


async def main():
    """Run the migration."""
    try:
        await add_tool_configs_column()
        print("\n✨ Migration completed successfully!")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
