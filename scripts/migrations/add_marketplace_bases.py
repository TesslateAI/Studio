"""
Marketplace Bases Migration

Creates tables for the Bases marketplace system:
- marketplace_bases: Project templates available in marketplace
- user_purchased_bases: Tracks user's base library
- base_reviews: User reviews for bases
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
    """Create marketplace bases tables."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("=== Creating Marketplace Bases Tables ===\n")

        try:
            # Create marketplace_bases table
            print("Creating marketplace_bases table...")
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS marketplace_bases (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    slug VARCHAR UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    long_description TEXT,
                    git_repo_url VARCHAR(500) NOT NULL,
                    default_branch VARCHAR(100) DEFAULT 'main',
                    category VARCHAR NOT NULL,
                    icon VARCHAR DEFAULT '📦',
                    preview_image VARCHAR,
                    tags JSON,
                    pricing_type VARCHAR NOT NULL DEFAULT 'free',
                    price INTEGER DEFAULT 0,
                    stripe_price_id VARCHAR,
                    stripe_product_id VARCHAR,
                    downloads INTEGER DEFAULT 0,
                    rating FLOAT DEFAULT 5.0,
                    reviews_count INTEGER DEFAULT 0,
                    features JSON,
                    tech_stack JSON,
                    is_featured BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_bases_slug ON marketplace_bases(slug);
            """))
            print("✓ marketplace_bases table created\n")

            # Create user_purchased_bases table
            print("Creating user_purchased_bases table...")
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS user_purchased_bases (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    base_id INTEGER NOT NULL REFERENCES marketplace_bases(id),
                    purchase_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    purchase_type VARCHAR NOT NULL,
                    stripe_payment_intent VARCHAR,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """))
            print("✓ user_purchased_bases table created\n")

            # Create base_reviews table
            print("Creating base_reviews table...")
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS base_reviews (
                    id SERIAL PRIMARY KEY,
                    base_id INTEGER NOT NULL REFERENCES marketplace_bases(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    rating INTEGER NOT NULL,
                    comment TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """))
            print("✓ base_reviews table created\n")

            await db.commit()
            print("=== Migration Complete! ===\n")

        except Exception as e:
            print(f"✗ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
