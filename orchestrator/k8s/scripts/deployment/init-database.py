#!/usr/bin/env python3
"""
Database initialization script for Kubernetes deployment.
Creates all tables defined in SQLAlchemy models.
"""
import asyncio
import sys
import os

# Add the orchestrator app to the path
sys.path.insert(0, '/app')

from app.database import engine, Base
from app.models import User, Project, ProjectFile, Chat, Message, RefreshToken


async def init_database():
    """Initialize database tables."""
    print("Starting database initialization...")
    print(f"Database URL: {os.getenv('DATABASE_URL', 'Not set')}")

    try:
        # Import all models to ensure they're registered with Base
        print("Models loaded:")
        print(f"  - User")
        print(f"  - Project")
        print(f"  - ProjectFile")
        print(f"  - Chat")
        print(f"  - Message")
        print(f"  - RefreshToken")

        # Create all tables
        print("\nCreating tables...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        print("✓ Database tables created successfully!")
        return 0

    except Exception as e:
        print(f"✗ Error initializing database: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(init_database())
    sys.exit(exit_code)
