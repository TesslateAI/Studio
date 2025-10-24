"""
Add API pricing fields to MarketplaceAgent
This adds fields for per-token pricing (input/output)
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings


async def run_migration():
    """Add API pricing fields to marketplace_agents table."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Adding API Pricing Fields to MarketplaceAgent ===\n")

        try:
            # Add api_pricing_input column ($ per million input tokens)
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS api_pricing_input FLOAT DEFAULT 0.0;
            """))
            print("✓ Added api_pricing_input column")

            # Add api_pricing_output column ($ per million output tokens)
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS api_pricing_output FLOAT DEFAULT 0.0;
            """))
            print("✓ Added api_pricing_output column")

            # Add created_by_user_id column to track Tesslate vs user-created agents
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(id);
            """))
            print("✓ Added created_by_user_id column")

            await db.commit()
            print("\n=== Migration completed successfully! ===\n")

        except Exception as e:
            print(f"\n❌ Migration failed: {e}\n")
            await db.rollback()
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())