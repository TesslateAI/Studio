"""
Migration: Add selected_model column to user_purchased_agents table

This allows users to override the model for open source agents in their library.
"""

import asyncio
import sys
import os
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.database import async_engine


async def migrate():
    """Add selected_model column to user_purchased_agents table."""
    async with async_engine.begin() as conn:
        print("Adding selected_model column to user_purchased_agents...")

        await conn.execute(text("""
            ALTER TABLE user_purchased_agents
            ADD COLUMN IF NOT EXISTS selected_model VARCHAR;
        """))

        print("Migration completed successfully!")


async def rollback():
    """Remove selected_model column from user_purchased_agents table."""
    async with async_engine.begin() as conn:
        print("Removing selected_model column from user_purchased_agents...")

        await conn.execute(text("""
            ALTER TABLE user_purchased_agents
            DROP COLUMN IF EXISTS selected_model;
        """))

        print("Rollback completed successfully!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        asyncio.run(rollback())
    else:
        asyncio.run(migrate())
