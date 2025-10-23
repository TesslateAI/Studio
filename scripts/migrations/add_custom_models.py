"""
Migration: Add user_custom_models table for OpenRouter custom models

Run with: python scripts/migrations/add_custom_models.py
"""

import asyncio
import sys
import os

# Add parent directory to path to import from orchestrator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
from orchestrator.app.database import engine


async def migrate():
    """Create user_custom_models table."""
    async with engine.begin() as conn:
        print("Creating user_custom_models table...")

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_custom_models (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                model_id VARCHAR NOT NULL,
                model_name VARCHAR NOT NULL,
                provider VARCHAR NOT NULL DEFAULT 'openrouter',
                pricing_input FLOAT,
                pricing_output FLOAT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(user_id, model_id, is_active)
            );
        """))

        print("Creating indexes...")
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_user_custom_models_user_id
            ON user_custom_models(user_id);

            CREATE INDEX IF NOT EXISTS idx_user_custom_models_provider
            ON user_custom_models(provider);
        """))

        print("✅ Migration completed successfully!")


async def rollback():
    """Rollback the migration."""
    async with engine.begin() as conn:
        print("Rolling back user_custom_models table...")

        await conn.execute(text("""
            DROP TABLE IF EXISTS user_custom_models CASCADE;
        """))

        print("✅ Rollback completed successfully!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("Rolling back migration...")
        asyncio.run(rollback())
    else:
        print("Running migration...")
        asyncio.run(migrate())
