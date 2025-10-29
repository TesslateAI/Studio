"""
Migration: Add comprehensive kanban board system

This migration adds:
- kanban_boards: Board per project
- kanban_columns: Customizable columns (Backlog, To Do, In Progress, Done, etc.)
- kanban_tasks: Rich tasks with metadata, assignments, priorities, etc.
- kanban_task_comments: Collaboration via comments
- project_notes: Separate rich text notes per project
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import text
try:
    # Container path (running from /app)
    from app.database import AsyncSessionLocal
except ModuleNotFoundError:
    # Local path (running from repo root)
    from orchestrator.app.database import AsyncSessionLocal


async def migrate():
    """Add kanban board system tables."""
    async with AsyncSessionLocal() as db:
        try:
            print("Creating kanban system tables...")

            # Create kanban_boards table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS kanban_boards (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                    name VARCHAR NOT NULL DEFAULT 'Project Board',
                    description TEXT,
                    settings JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            print("✅ Created kanban_boards table")

            # Create kanban_columns table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS kanban_columns (
                    id SERIAL PRIMARY KEY,
                    board_id INTEGER NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
                    name VARCHAR NOT NULL,
                    description TEXT,
                    position INTEGER NOT NULL,
                    color VARCHAR,
                    icon VARCHAR,
                    is_backlog BOOLEAN DEFAULT FALSE,
                    is_completed BOOLEAN DEFAULT FALSE,
                    task_limit INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            print("✅ Created kanban_columns table")

            # Create kanban_tasks table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS kanban_tasks (
                    id SERIAL PRIMARY KEY,
                    board_id INTEGER NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
                    column_id INTEGER NOT NULL REFERENCES kanban_columns(id) ON DELETE CASCADE,
                    title VARCHAR NOT NULL,
                    description TEXT,
                    position INTEGER NOT NULL,
                    priority VARCHAR,
                    status VARCHAR,
                    task_type VARCHAR,
                    tags JSONB,
                    assignee_id INTEGER REFERENCES users(id),
                    reporter_id INTEGER REFERENCES users(id),
                    estimate_hours INTEGER,
                    spent_hours INTEGER,
                    due_date TIMESTAMP WITH TIME ZONE,
                    started_at TIMESTAMP WITH TIME ZONE,
                    completed_at TIMESTAMP WITH TIME ZONE,
                    custom_fields JSONB,
                    attachments JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            print("✅ Created kanban_tasks table")

            # Create kanban_task_comments table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS kanban_task_comments (
                    id SERIAL PRIMARY KEY,
                    task_id INTEGER NOT NULL REFERENCES kanban_tasks(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            print("✅ Created kanban_task_comments table")

            # Create project_notes table
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS project_notes (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                    content TEXT,
                    content_format VARCHAR DEFAULT 'html',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            print("✅ Created project_notes table")

            # Create indexes for better query performance (one at a time for asyncpg)
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_kanban_boards_project_id ON kanban_boards(project_id)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_columns_board_id ON kanban_columns(board_id)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_columns_position ON kanban_columns(board_id, position)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_tasks_board_id ON kanban_tasks(board_id)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_tasks_column_id ON kanban_tasks(column_id)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_tasks_position ON kanban_tasks(column_id, position)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_tasks_assignee_id ON kanban_tasks(assignee_id)",
                "CREATE INDEX IF NOT EXISTS idx_kanban_task_comments_task_id ON kanban_task_comments(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_project_notes_project_id ON project_notes(project_id)"
            ]
            for index_sql in indexes:
                await db.execute(text(index_sql))
            print("✅ Created indexes")

            await db.commit()
            print("\n✅ Migration completed successfully!")
            print("\nNext steps:")
            print("1. Boards will be auto-created for projects on first access")
            print("2. Default columns (Backlog, To Do, In Progress, Done) will be created")
            print("3. Users can customize columns and tasks through the UI")

        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
