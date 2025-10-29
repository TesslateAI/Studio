"""
User API Keys Migration

Creates the user_api_keys table for comprehensive secrets management.
This table stores API keys and OAuth tokens for various providers
(OpenRouter, Anthropic, OpenAI, Google, GitHub, etc.)
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
    """Create user_api_keys table and add selected_model column to user_purchased_agents."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("=== Creating User API Keys Table ===\n")

        try:
            # Create user_api_keys table
            print("Creating user_api_keys table...")
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS user_api_keys (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    provider VARCHAR NOT NULL,
                    auth_type VARCHAR NOT NULL DEFAULT 'api_key',
                    key_name VARCHAR,
                    encrypted_value TEXT NOT NULL,
                    provider_metadata JSONB DEFAULT '{}',
                    is_active BOOLEAN DEFAULT TRUE,
                    expires_at TIMESTAMP WITH TIME ZONE,
                    last_used_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(user_id, provider, key_name)
                );

                CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id ON user_api_keys(user_id);
                CREATE INDEX IF NOT EXISTS idx_user_api_keys_provider ON user_api_keys(provider);

                COMMENT ON TABLE user_api_keys IS 'Stores user API keys and OAuth tokens for various providers';
                COMMENT ON COLUMN user_api_keys.provider IS 'Provider name: openrouter, anthropic, openai, google, github, etc.';
                COMMENT ON COLUMN user_api_keys.auth_type IS 'Authentication type: api_key, oauth_token, bearer_token, personal_access_token';
                COMMENT ON COLUMN user_api_keys.key_name IS 'Optional name for the key (useful when user has multiple keys for same provider)';
                COMMENT ON COLUMN user_api_keys.provider_metadata IS 'Provider-specific metadata: refresh_token, scopes, token_type, etc.';
            """))
            print("✓ user_api_keys table created\n")

            # Add selected_model column to user_purchased_agents if not exists
            print("Adding selected_model column to user_purchased_agents...")
            await db.execute(text("""
                ALTER TABLE user_purchased_agents
                ADD COLUMN IF NOT EXISTS selected_model VARCHAR;

                COMMENT ON COLUMN user_purchased_agents.selected_model IS 'User-selected model override for open source agents';
            """))
            print("✓ selected_model column added\n")

            await db.commit()
            print("=== Migration Complete! ===\n")
            print("API Keys Management System Ready:")
            print("  • user_api_keys table created")
            print("  • Support for multiple providers (OpenRouter, Anthropic, OpenAI, Google, GitHub, etc.)")
            print("  • OAuth and API key authentication types")
            print("  • Model selection per agent enabled\n")

        except Exception as e:
            print(f"✗ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
