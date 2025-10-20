"""
Add missing columns to marketplace_agents table migration script.
"""

import asyncio
from sqlalchemy import text
from app.database import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def add_missing_columns():
    """Add source_type and requires_user_keys columns if they don't exist."""
    try:
        async with engine.begin() as conn:
            # Check if columns already exist
            result = await conn.execute(text("PRAGMA table_info(marketplace_agents)"))
            columns = [row[1] for row in result]

            if 'source_type' not in columns:
                logger.info("Adding source_type column...")
                await conn.execute(text("""
                    ALTER TABLE marketplace_agents
                    ADD COLUMN source_type VARCHAR DEFAULT 'closed'
                """))
                logger.info("Added source_type column successfully")
            else:
                logger.info("source_type column already exists")

            if 'requires_user_keys' not in columns:
                logger.info("Adding requires_user_keys column...")
                await conn.execute(text("""
                    ALTER TABLE marketplace_agents
                    ADD COLUMN requires_user_keys BOOLEAN DEFAULT 0
                """))
                logger.info("Added requires_user_keys column successfully")
            else:
                logger.info("requires_user_keys column already exists")

            # Update existing agents with the correct values
            logger.info("Updating existing agents with source_type and requires_user_keys values...")

            # Set source_type and requires_user_keys based on pricing_type
            await conn.execute(text("""
                UPDATE marketplace_agents
                SET source_type = 'open',
                    requires_user_keys = 1
                WHERE pricing_type = 'passthrough'
            """))

            await conn.execute(text("""
                UPDATE marketplace_agents
                SET source_type = 'closed',
                    requires_user_keys = 0
                WHERE pricing_type IN ('monthly', 'usage')
            """))

            await conn.execute(text("""
                UPDATE marketplace_agents
                SET source_type = CASE
                    WHEN name IN ('Builder AI Pro', 'Frontend Master') THEN 'open'
                    ELSE 'closed'
                END,
                requires_user_keys = CASE
                    WHEN name = 'Builder AI Pro' THEN 1
                    ELSE 0
                END
                WHERE pricing_type = 'free'
            """))

            logger.info("Migration completed successfully!")
            return True

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False


async def main():
    """Main function to run the migration."""
    logger.info("Starting column addition migration...")
    success = await add_missing_columns()
    if success:
        logger.info("All columns added successfully!")
    else:
        logger.error("Migration failed!")


if __name__ == "__main__":
    asyncio.run(main())