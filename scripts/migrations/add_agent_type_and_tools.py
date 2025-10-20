"""
Database Migration: Add agent_type and tools columns to marketplace_agents

This migration adds:
1. agent_type column - specifies which agent class to use (StreamAgent, IterativeAgent, etc.)
2. tools column (JSON) - specifies which tools this agent has access to

Run with: python scripts/migrations/add_agent_type_and_tools.py
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from orchestrator.app.config import get_settings


async def migrate():
    """Run the migration to add agent_type and tools columns."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        try:
            print("\n=== Starting Migration ===\n")

            # Check if columns already exist
            print("Checking if columns exist...")
            result = await db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'marketplace_agents'
                AND column_name IN ('agent_type', 'tools')
            """))
            existing_columns = [row[0] for row in result.fetchall()]

            # Add agent_type column if it doesn't exist
            if 'agent_type' not in existing_columns:
                print("\n1. Adding agent_type column...")
                await db.execute(text("""
                    ALTER TABLE marketplace_agents
                    ADD COLUMN agent_type VARCHAR NOT NULL DEFAULT 'StreamAgent'
                """))
                print("   ✅ agent_type column added")
            else:
                print("\n1. agent_type column already exists, skipping")

            # Add tools column if it doesn't exist
            if 'tools' not in existing_columns:
                print("\n2. Adding tools column...")
                await db.execute(text("""
                    ALTER TABLE marketplace_agents
                    ADD COLUMN tools JSON
                """))
                print("   ✅ tools column added")
            else:
                print("\n2. tools column already exists, skipping")

            # Migrate existing data: Set agent_type based on mode
            print("\n3. Migrating existing agent data...")
            print("   Setting agent_type based on mode column...")

            # Agents with mode='stream' -> agent_type='StreamAgent'
            result = await db.execute(text("""
                UPDATE marketplace_agents
                SET agent_type = 'StreamAgent'
                WHERE mode = 'stream' AND (agent_type IS NULL OR agent_type = 'StreamAgent')
            """))
            stream_count = result.rowcount
            print(f"   ✅ Updated {stream_count} stream agents to StreamAgent")

            # Agents with mode='agent' -> agent_type='IterativeAgent'
            result = await db.execute(text("""
                UPDATE marketplace_agents
                SET agent_type = 'IterativeAgent'
                WHERE mode = 'agent' AND (agent_type IS NULL OR agent_type = 'StreamAgent')
            """))
            agent_count = result.rowcount
            print(f"   ✅ Updated {agent_count} agent mode agents to IterativeAgent")

            # Commit the changes
            await db.commit()
            print("\n=== Migration Completed Successfully ===\n")

            # Show summary
            print("Summary:")
            print(f"  - Added agent_type column (if missing)")
            print(f"  - Added tools column (if missing)")
            print(f"  - Migrated {stream_count} StreamAgent entries")
            print(f"  - Migrated {agent_count} IterativeAgent entries")
            print()
            print("Notes:")
            print("  - The 'mode' column is kept for backwards compatibility")
            print("  - New agents should use 'agent_type' to specify their class")
            print("  - The 'tools' column can be set to restrict available tools")
            print()

        except Exception as e:
            await db.rollback()
            print(f"\n❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            raise


async def show_agents():
    """Show all agents and their types."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT name, mode, agent_type,
                   CASE WHEN tools IS NULL THEN 'NULL' ELSE 'SET' END as tools_status
            FROM marketplace_agents
            ORDER BY id
        """))

        print("\n=== Current Agents ===")
        print(f"{'Name':<30} {'Mode':<10} {'Agent Type':<20} {'Tools':<10}")
        print("-" * 70)
        for row in result.fetchall():
            print(f"{row[0]:<30} {row[1]:<10} {row[2]:<20} {row[3]:<10}")
        print()


if __name__ == "__main__":
    print("MarketplaceAgent Migration Script")
    print("=" * 50)

    if len(sys.argv) > 1 and sys.argv[1] == "--show":
        asyncio.run(show_agents())
    else:
        asyncio.run(migrate())
        print("\nRun with --show to see current agent types")
