"""
Migration script to add ON DELETE CASCADE to foreign key constraints on projects table.

This fixes the issue where deleting a project fails due to foreign key violations
from dependent tables (shell_sessions, chats, agent_command_logs).

Run this script to update the foreign key constraints to cascade deletes.
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
from app.database import engine


async def run_migration():
    """Add ON DELETE CASCADE to project foreign key constraints."""

    async with engine.begin() as conn:
        print("Updating foreign key constraints to cascade deletes on projects table...")

        # List of tables and their foreign key constraints to update
        constraints_to_update = [
            {
                "table": "shell_sessions",
                "constraint": "shell_sessions_project_id_fkey",
                "column": "project_id"
            },
            {
                "table": "chats",
                "constraint": "chats_project_id_fkey",
                "column": "project_id"
            },
            {
                "table": "agent_command_logs",
                "constraint": "agent_command_logs_project_id_fkey",
                "column": "project_id"
            }
        ]

        for constraint_info in constraints_to_update:
            table = constraint_info["table"]
            constraint = constraint_info["constraint"]
            column = constraint_info["column"]

            # Check if constraint exists
            result = await conn.execute(text(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = :constraint_name
                    AND table_name = :table_name
                );
                """
            ), {"constraint_name": constraint, "table_name": table})

            constraint_exists = result.scalar()

            if not constraint_exists:
                print(f"  ⚠️  Constraint '{constraint}' on '{table}' does not exist. Skipping.")
                continue

            print(f"  Updating {table}.{column} constraint...")

            try:
                # Drop the old constraint
                await conn.execute(text(
                    f"ALTER TABLE {table} DROP CONSTRAINT {constraint};"
                ))

                # Add the new constraint with ON DELETE CASCADE
                await conn.execute(text(
                    f"""
                    ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    FOREIGN KEY ({column})
                    REFERENCES projects(id)
                    ON DELETE CASCADE;
                    """
                ))

                print(f"  ✓ Successfully updated {table}.{column}")

            except Exception as e:
                print(f"  ✗ Error updating {table}.{column}: {e}")
                raise

        print("\n✓ Migration completed successfully!")
        print("\nThe following foreign keys now cascade deletes:")
        print("  - shell_sessions.project_id -> projects.id")
        print("  - chats.project_id -> projects.id")
        print("  - agent_command_logs.project_id -> projects.id")
        print("\nDeleting a project will now automatically delete all related records.")


async def rollback_migration():
    """Remove ON DELETE CASCADE from project foreign key constraints."""

    async with engine.begin() as conn:
        print("Removing ON DELETE CASCADE from foreign key constraints...")

        constraints_to_update = [
            {
                "table": "shell_sessions",
                "constraint": "shell_sessions_project_id_fkey",
                "column": "project_id"
            },
            {
                "table": "chats",
                "constraint": "chats_project_id_fkey",
                "column": "project_id"
            },
            {
                "table": "agent_command_logs",
                "constraint": "agent_command_logs_project_id_fkey",
                "column": "project_id"
            }
        ]

        for constraint_info in constraints_to_update:
            table = constraint_info["table"]
            constraint = constraint_info["constraint"]
            column = constraint_info["column"]

            print(f"  Reverting {table}.{column} constraint...")

            try:
                # Drop the cascade constraint
                await conn.execute(text(
                    f"ALTER TABLE {table} DROP CONSTRAINT {constraint};"
                ))

                # Add back without CASCADE
                await conn.execute(text(
                    f"""
                    ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    FOREIGN KEY ({column})
                    REFERENCES projects(id);
                    """
                ))

                print(f"  ✓ Successfully reverted {table}.{column}")

            except Exception as e:
                print(f"  ✗ Error reverting {table}.{column}: {e}")
                raise

        print("\n✓ Rollback completed successfully!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("Running rollback...")
        asyncio.run(rollback_migration())
    else:
        print("Running migration...")
        asyncio.run(run_migration())
