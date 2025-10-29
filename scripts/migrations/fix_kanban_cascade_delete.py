"""
Migration: Fix cascade delete for kanban_boards and project_notes

This migration updates the foreign key constraints to properly cascade deletes
when a project is deleted.

Run this with:
    python scripts/migrations/fix_kanban_cascade_delete.py
"""

import asyncio
import sys
import os

# Add parent directory to path to import from orchestrator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from orchestrator.app.database import engine
from sqlalchemy import text


async def run_migration():
    """Apply the migration to fix cascade delete constraints."""

    async with engine.begin() as conn:
        print("[MIGRATION] Starting cascade delete fix for kanban tables...")

        # Fix kanban_boards foreign key constraint
        print("[MIGRATION] Dropping old kanban_boards constraint...")
        await conn.execute(text("""
            ALTER TABLE kanban_boards
            DROP CONSTRAINT IF EXISTS kanban_boards_project_id_fkey;
        """))

        print("[MIGRATION] Adding new kanban_boards constraint with CASCADE...")
        await conn.execute(text("""
            ALTER TABLE kanban_boards
            ADD CONSTRAINT kanban_boards_project_id_fkey
            FOREIGN KEY (project_id)
            REFERENCES projects(id)
            ON DELETE CASCADE;
        """))

        # Fix project_notes foreign key constraint
        print("[MIGRATION] Dropping old project_notes constraint...")
        await conn.execute(text("""
            ALTER TABLE project_notes
            DROP CONSTRAINT IF EXISTS project_notes_project_id_fkey;
        """))

        print("[MIGRATION] Adding new project_notes constraint with CASCADE...")
        await conn.execute(text("""
            ALTER TABLE project_notes
            ADD CONSTRAINT project_notes_project_id_fkey
            FOREIGN KEY (project_id)
            REFERENCES projects(id)
            ON DELETE CASCADE;
        """))

        print("[MIGRATION] Migration completed successfully!")
        print("[MIGRATION] Now when you delete a project, all related kanban boards and notes will be automatically deleted.")


if __name__ == "__main__":
    print("=" * 60)
    print("Migration: Fix Cascade Delete for Kanban Tables")
    print("=" * 60)
    asyncio.run(run_migration())
    print("=" * 60)
