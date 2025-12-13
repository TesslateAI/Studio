"""
Database migration script: Add Container and ContainerConnection models

This script adds support for multi-container monorepo projects with:
- containers table: Each base becomes a containerized service
- container_connections table: Dependencies between containers (for React Flow edges)
- network_name column in projects table: Docker network for container communication

Run this script to update the database schema for the new node graph feature.
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
from app.database import AsyncSessionLocal, engine


async def run_migration():
    """Execute the database migration."""
    print("[MIGRATION] Starting migration: add_container_models")
    print("[MIGRATION] This will add containers and container_connections tables")

    async with AsyncSessionLocal() as db:
        try:
            # Check if migration is already applied
            print("\n[CHECK] Checking if migration is already applied...")
            result = await db.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'containers'
                    );
                """)
            )
            exists = result.scalar()

            if exists:
                print("[SKIP] Migration already applied (containers table exists)")
                return

            print("\n[STEP 1/4] Adding network_name column to projects table...")
            await db.execute(
                text("""
                    ALTER TABLE projects
                    ADD COLUMN IF NOT EXISTS network_name VARCHAR;
                """)
            )
            await db.commit()
            print("[SUCCESS] network_name column added")

            print("\n[STEP 2/4] Creating containers table...")
            await db.execute(
                text("""
                    CREATE TABLE containers (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        base_id UUID REFERENCES marketplace_bases(id) ON DELETE SET NULL,

                        name VARCHAR NOT NULL,
                        directory VARCHAR NOT NULL,
                        container_name VARCHAR NOT NULL,

                        port INTEGER,
                        internal_port INTEGER,
                        environment_vars JSONB,
                        dockerfile_path VARCHAR,

                        position_x DOUBLE PRECISION DEFAULT 0,
                        position_y DOUBLE PRECISION DEFAULT 0,

                        status VARCHAR DEFAULT 'stopped',
                        last_started_at TIMESTAMP WITH TIME ZONE,

                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    );
                """)
            )
            await db.commit()
            print("[SUCCESS] containers table created")

            print("\n[STEP 3/4] Creating container_connections table...")
            await db.execute(
                text("""
                    CREATE TABLE container_connections (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        source_container_id UUID NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
                        target_container_id UUID NOT NULL REFERENCES containers(id) ON DELETE CASCADE,

                        connection_type VARCHAR DEFAULT 'depends_on',
                        label VARCHAR,

                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    );
                """)
            )
            await db.commit()
            print("[SUCCESS] container_connections table created")

            print("\n[STEP 4/4] Creating indexes...")
            await db.execute(
                text("""
                    CREATE INDEX idx_containers_project_id ON containers(project_id);
                    CREATE INDEX idx_containers_base_id ON containers(base_id);
                    CREATE INDEX idx_container_connections_project_id ON container_connections(project_id);
                    CREATE INDEX idx_container_connections_source ON container_connections(source_container_id);
                    CREATE INDEX idx_container_connections_target ON container_connections(target_container_id);
                """)
            )
            await db.commit()
            print("[SUCCESS] Indexes created")

            print("\n[MIGRATION] ✅ Migration completed successfully!")
            print("[NEXT STEPS]:")
            print("  1. Restart the orchestrator service")
            print("  2. Create your first multi-container project")
            print("  3. Drag bases onto the React Flow canvas")

        except Exception as e:
            await db.rollback()
            print(f"\n[ERROR] ❌ Migration failed: {e}")
            raise


if __name__ == "__main__":
    print("=" * 70)
    print("  Database Migration: Multi-Container Project Support")
    print("=" * 70)
    asyncio.run(run_migration())
