#!/usr/bin/env python3
"""
Add 'name' column to users table for existing users.

This script adds the name column and sets default values based on username.
"""

import asyncio
import sys
import os

# Add the orchestrator app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator', 'app'))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def add_name_column():
    """Add name column to users table."""

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)

    async with engine.begin() as conn:
        try:
            # Check if column already exists
            result = await conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='name';
            """))

            exists = result.scalar_one_or_none()

            if exists:
                logger.info("Column 'name' already exists in users table")
                return

            # Add the name column (nullable first)
            logger.info("Adding 'name' column to users table...")
            await conn.execute(text("""
                ALTER TABLE users ADD COLUMN name VARCHAR;
            """))

            # Set default values (use username as name for existing users)
            logger.info("Setting default name values for existing users...")
            await conn.execute(text("""
                UPDATE users SET name = username WHERE name IS NULL;
            """))

            # Make it NOT NULL
            logger.info("Making 'name' column NOT NULL...")
            await conn.execute(text("""
                ALTER TABLE users ALTER COLUMN name SET NOT NULL;
            """))

            logger.info("✅ Successfully added 'name' column to users table")

        except Exception as e:
            logger.error(f"❌ Error adding name column: {e}")
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(add_name_column())
