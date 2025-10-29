"""Simple migration to add agent_type and tools columns"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.config import get_settings

async def migrate():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("=== Database Migration: Add agent_type and tools ===\n")

        # Check existing columns
        result = await db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'marketplace_agents'
            AND column_name IN ('agent_type', 'tools')
        """))
        existing = [row[0] for row in result.fetchall()]
        print(f"Existing columns: {existing}\n")

        # Add agent_type
        if 'agent_type' not in existing:
            print("Adding agent_type column...")
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN agent_type VARCHAR NOT NULL DEFAULT 'StreamAgent'
            """))
            print("✓ agent_type added\n")
        else:
            print("✓ agent_type already exists\n")

        # Add tools
        if 'tools' not in existing:
            print("Adding tools column...")
            await db.execute(text("""
                ALTER TABLE marketplace_agents
                ADD COLUMN tools JSON
            """))
            print("✓ tools added\n")
        else:
            print("✓ tools already exists\n")

        # Migrate existing data
        print("Migrating existing agent data...")
        result1 = await db.execute(text("""
            UPDATE marketplace_agents
            SET agent_type = 'StreamAgent'
            WHERE mode = 'stream'
        """))
        print(f"✓ Updated {result1.rowcount} stream agents")

        result2 = await db.execute(text("""
            UPDATE marketplace_agents
            SET agent_type = 'IterativeAgent'
            WHERE mode = 'agent'
        """))
        print(f"✓ Updated {result2.rowcount} iterative agents\n")

        await db.commit()
        print("=== Migration Complete! ===\n")

        # Show results
        result = await db.execute(text("""
            SELECT name, mode, agent_type,
                   CASE WHEN tools IS NULL THEN 'NULL' ELSE 'SET' END
            FROM marketplace_agents
        """))
        print("Current agents:")
        print(f"{'Name':<30} {'Mode':<10} {'Type':<20} {'Tools':<10}")
        print("-" * 70)
        for row in result.fetchall():
            print(f"{row[0]:<30} {row[1]:<10} {row[2]:<20} {row[3]:<10}")

asyncio.run(migrate())
