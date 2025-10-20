"""
Expand Marketplace Schema Migration

Adds new columns to support:
- Multiple item types (agents, bases, tools, integrations)
- Agent forking
- Model selection per agent
- User-created forked agents
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from orchestrator.app.config import get_settings


async def migrate():
    """Add new columns to marketplace_agents table."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("=== Expanding Marketplace Schema ===\n")

        try:
            # Add item_type column
            print("Adding item_type column...")
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS item_type VARCHAR NOT NULL DEFAULT 'agent'
            """))
            print("✓ item_type column added\n")

            # Add model column
            print("Adding model column...")
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS model VARCHAR
            """))
            print("✓ model column added\n")

            # Add forking columns
            print("Adding forking columns...")
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS is_forkable BOOLEAN DEFAULT FALSE
            """))
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS parent_agent_id INTEGER REFERENCES marketplace_agents(id)
            """))
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS forked_by_user_id INTEGER REFERENCES users(id)
            """))
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS config JSON
            """))
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS is_published BOOLEAN DEFAULT TRUE
            """))
            print("✓ Forking columns added\n")

            # Make agent-specific fields nullable
            print("Making agent-specific fields nullable...")
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ALTER COLUMN system_prompt DROP NOT NULL
            """))
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ALTER COLUMN mode DROP NOT NULL
            """))
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ALTER COLUMN agent_type DROP NOT NULL
            """))
            print("✓ Fields made nullable\n")

            await db.commit()
            print("=== Migration Complete! ===\n")

        except Exception as e:
            print(f"✗ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
