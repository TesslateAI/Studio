"""
Migration script to add shell_sessions table.

Run this script to add the ShellSession model to your database.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

# Override DATABASE_URL for local execution (connect to localhost instead of docker network)
if "DATABASE_URL" in os.environ:
    os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].replace("@postgres:", "@localhost:")

from sqlalchemy import text
from app.database import engine, Base
from app.models import ShellSession


async def run_migration():
    """Create shell_sessions table."""

    async with engine.begin() as conn:
        # Check if table already exists
        result = await conn.execute(text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'shell_sessions'
            );
            """
        ))
        table_exists = result.scalar()

        if table_exists:
            print("Table 'shell_sessions' already exists. Skipping migration.")
            return

        print("Creating shell_sessions table...")

        # Create the table
        await conn.run_sync(Base.metadata.tables['shell_sessions'].create)

        print("Successfully created shell_sessions table!")
        print("\nTable schema:")
        print("  - id (primary key)")
        print("  - session_id (unique, indexed)")
        print("  - user_id (foreign key -> users.id)")
        print("  - project_id (foreign key -> projects.id)")
        print("  - container_name")
        print("  - command (default: /bin/bash)")
        print("  - working_dir (default: /app/project)")
        print("  - terminal_rows (default: 24)")
        print("  - terminal_cols (default: 80)")
        print("  - status (default: initializing)")
        print("  - created_at (auto timestamp)")
        print("  - last_activity_at (auto timestamp)")
        print("  - closed_at (nullable)")
        print("  - bytes_read (default: 0)")
        print("  - bytes_written (default: 0)")
        print("  - total_reads (default: 0)")


async def rollback_migration():
    """Drop shell_sessions table."""

    async with engine.begin() as conn:
        result = await conn.execute(text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'shell_sessions'
            );
            """
        ))
        table_exists = result.scalar()

        if not table_exists:
            print("Table 'shell_sessions' does not exist. Nothing to rollback.")
            return

        print("Dropping shell_sessions table...")
        await conn.execute(text("DROP TABLE shell_sessions;"))
        print("Successfully dropped shell_sessions table!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("Running rollback...")
        asyncio.run(rollback_migration())
    else:
        print("Running migration...")
        asyncio.run(run_migration())
