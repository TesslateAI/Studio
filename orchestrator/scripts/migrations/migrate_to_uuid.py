"""
Migration: Convert Integer IDs to UUIDs

This migration converts all primary keys and foreign keys from sequential integers to UUIDs.

Benefits:
- Non-enumerable (secure)
- Collision-free
- Distributed system compatible
- No information leakage about record counts

WARNING: This is a DESTRUCTIVE migration that will:
1. Create new UUID columns
2. Generate UUIDs for existing records
3. Update all foreign key references
4. Drop old integer columns
5. Rename UUID columns to original names

IMPORTANT:
- Backup your database before running this migration
- Test on a staging environment first
- This migration cannot be easily rolled back
- Existing container names will become invalid (they use old integer IDs)

Usage:
    python scripts/migrations/migrate_to_uuid.py
"""

import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.config import get_settings


async def migrate():
    """Convert all integer IDs to UUIDs."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n" + "="*80)
        print("MIGRATION: Convert Integer IDs to UUIDs")
        print("="*80)
        print("\n⚠️  WARNING: This is a DESTRUCTIVE migration!")
        print("Please confirm you have:")
        print("  1. Backed up your database")
        print("  2. Tested on staging environment")
        print("  3. Stopped all running containers/pods")
        print("\nType 'YES' to continue: ", end="")

        confirmation = input()
        if confirmation != "YES":
            print("\n❌ Migration cancelled.")
            return

        try:
            print("\n" + "-"*80)
            print("Step 1: Add UUID extension to PostgreSQL")
            print("-"*80)
            await db.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await db.commit()
            print("✓ UUID extension enabled\n")

            print("-"*80)
            print("Step 2: Create UUID columns for all tables")
            print("-"*80)

            # Core tables
            tables_to_migrate = [
                "users",
                "projects",
                "project_files",
                "chats",
                "messages",
                "refresh_tokens",
                "agent_command_logs",
                "pod_access_logs",
                "shell_sessions",
                "github_credentials",
                "git_repositories",
                "marketplace_agents",
                "user_purchased_agents",
                "project_agents",
                "agent_reviews",
                "marketplace_bases",
                "user_purchased_bases",
                "base_reviews",
                "user_api_keys",
                "user_custom_models",
                "kanban_boards",
                "kanban_columns",
                "kanban_tasks",
                "kanban_task_comments",
                "project_notes"
            ]

            for table in tables_to_migrate:
                print(f"Adding uuid column to {table}...")
                await db.execute(text(f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS id_uuid UUID DEFAULT uuid_generate_v4()
                """))
            await db.commit()
            print("✓ UUID columns added\n")

            print("-"*80)
            print("Step 3: Generate UUIDs for existing records")
            print("-"*80)
            for table in tables_to_migrate:
                print(f"Generating UUIDs for {table}...")
                await db.execute(text(f"""
                    UPDATE {table}
                    SET id_uuid = uuid_generate_v4()
                    WHERE id_uuid IS NULL
                """))
            await db.commit()
            print("✓ UUIDs generated\n")

            print("-"*80)
            print("Step 4: Create temporary mapping tables")
            print("-"*80)
            # Create mapping tables to preserve relationships
            await db.execute(text("""
                CREATE TEMP TABLE user_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM users
            """))
            await db.execute(text("""
                CREATE TEMP TABLE project_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM projects
            """))
            await db.execute(text("""
                CREATE TEMP TABLE chat_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM chats
            """))
            await db.execute(text("""
                CREATE TEMP TABLE agent_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM marketplace_agents
            """))
            await db.execute(text("""
                CREATE TEMP TABLE base_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM marketplace_bases
            """))
            await db.execute(text("""
                CREATE TEMP TABLE board_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM kanban_boards
            """))
            await db.execute(text("""
                CREATE TEMP TABLE column_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM kanban_columns
            """))
            await db.execute(text("""
                CREATE TEMP TABLE task_id_mapping AS
                SELECT id as old_id, id_uuid as new_id FROM kanban_tasks
            """))
            print("✓ Mapping tables created\n")

            print("-"*80)
            print("Step 5: Create new UUID foreign key columns")
            print("-"*80)

            # Foreign key columns to migrate
            fk_columns = [
                # (table, column, references_table)
                ("projects", "owner_id", "users"),
                ("project_files", "project_id", "projects"),
                ("chats", "user_id", "users"),
                ("chats", "project_id", "projects"),
                ("messages", "chat_id", "chats"),
                ("refresh_tokens", "user_id", "users"),
                ("agent_command_logs", "user_id", "users"),
                ("agent_command_logs", "project_id", "projects"),
                ("pod_access_logs", "user_id", "users"),
                ("pod_access_logs", "expected_user_id", "users"),
                ("pod_access_logs", "project_id", "projects"),
                ("shell_sessions", "user_id", "users"),
                ("shell_sessions", "project_id", "projects"),
                ("github_credentials", "user_id", "users"),
                ("git_repositories", "project_id", "projects"),
                ("git_repositories", "user_id", "users"),
                ("marketplace_agents", "parent_agent_id", "marketplace_agents"),
                ("marketplace_agents", "forked_by_user_id", "users"),
                ("marketplace_agents", "created_by_user_id", "users"),
                ("user_purchased_agents", "user_id", "users"),
                ("user_purchased_agents", "agent_id", "marketplace_agents"),
                ("project_agents", "project_id", "projects"),
                ("project_agents", "agent_id", "marketplace_agents"),
                ("project_agents", "user_id", "users"),
                ("agent_reviews", "agent_id", "marketplace_agents"),
                ("agent_reviews", "user_id", "users"),
                ("user_purchased_bases", "user_id", "users"),
                ("user_purchased_bases", "base_id", "marketplace_bases"),
                ("base_reviews", "base_id", "marketplace_bases"),
                ("base_reviews", "user_id", "users"),
                ("user_api_keys", "user_id", "users"),
                ("user_custom_models", "user_id", "users"),
                ("kanban_boards", "project_id", "projects"),
                ("kanban_columns", "board_id", "kanban_boards"),
                ("kanban_tasks", "board_id", "kanban_boards"),
                ("kanban_tasks", "column_id", "kanban_columns"),
                ("kanban_tasks", "assignee_id", "users"),
                ("kanban_tasks", "reporter_id", "users"),
                ("kanban_task_comments", "task_id", "kanban_tasks"),
                ("kanban_task_comments", "user_id", "users"),
                ("project_notes", "project_id", "projects"),
            ]

            for table, column, ref_table in fk_columns:
                print(f"Adding UUID FK column to {table}.{column}...")
                await db.execute(text(f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS {column}_uuid UUID
                """))
            await db.commit()
            print("✓ UUID FK columns added\n")

            print("-"*80)
            print("Step 6: Populate UUID foreign keys using mappings")
            print("-"*80)

            # Update foreign keys using mapping tables
            fk_updates = [
                ("projects", "owner_id", "user"),
                ("project_files", "project_id", "project"),
                ("chats", "user_id", "user"),
                ("chats", "project_id", "project"),
                ("messages", "chat_id", "chat"),
                ("refresh_tokens", "user_id", "user"),
                ("agent_command_logs", "user_id", "user"),
                ("agent_command_logs", "project_id", "project"),
                ("pod_access_logs", "user_id", "user"),
                ("pod_access_logs", "expected_user_id", "user"),
                ("pod_access_logs", "project_id", "project"),
                ("shell_sessions", "user_id", "user"),
                ("shell_sessions", "project_id", "project"),
                ("github_credentials", "user_id", "user"),
                ("git_repositories", "project_id", "project"),
                ("git_repositories", "user_id", "user"),
                ("marketplace_agents", "parent_agent_id", "agent"),
                ("marketplace_agents", "forked_by_user_id", "user"),
                ("marketplace_agents", "created_by_user_id", "user"),
                ("user_purchased_agents", "user_id", "user"),
                ("user_purchased_agents", "agent_id", "agent"),
                ("project_agents", "project_id", "project"),
                ("project_agents", "agent_id", "agent"),
                ("project_agents", "user_id", "user"),
                ("agent_reviews", "agent_id", "agent"),
                ("agent_reviews", "user_id", "user"),
                ("user_purchased_bases", "user_id", "user"),
                ("user_purchased_bases", "base_id", "base"),
                ("base_reviews", "base_id", "base"),
                ("base_reviews", "user_id", "user"),
                ("user_api_keys", "user_id", "user"),
                ("user_custom_models", "user_id", "user"),
                ("kanban_boards", "project_id", "project"),
                ("kanban_columns", "board_id", "board"),
                ("kanban_tasks", "board_id", "board"),
                ("kanban_tasks", "column_id", "column"),
                ("kanban_tasks", "assignee_id", "user"),
                ("kanban_tasks", "reporter_id", "user"),
                ("kanban_task_comments", "task_id", "task"),
                ("kanban_task_comments", "user_id", "user"),
                ("project_notes", "project_id", "project"),
            ]

            for table, column, mapping_type in fk_updates:
                mapping_table = f"{mapping_type}_id_mapping"
                print(f"Updating {table}.{column}_uuid from {mapping_table}...")
                await db.execute(text(f"""
                    UPDATE {table} t
                    SET {column}_uuid = m.new_id
                    FROM {mapping_table} m
                    WHERE t.{column} = m.old_id
                """))
            await db.commit()
            print("✓ UUID foreign keys populated\n")

            print("-"*80)
            print("Step 7: Drop old foreign key constraints")
            print("-"*80)
            # Drop old constraints (varies by database schema)
            # This step may need to be customized based on your actual constraints
            print("Dropping old foreign key constraints...")
            print("(Skipping - will be handled in next step when columns are dropped)\n")

            print("-"*80)
            print("Step 8: Drop old integer ID columns and rename UUID columns")
            print("-"*80)

            # Drop old ID columns and rename UUID columns
            for table in tables_to_migrate:
                print(f"Migrating {table}...")
                # Drop old ID column
                await db.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS id CASCADE"))
                # Rename UUID column to id
                await db.execute(text(f"ALTER TABLE {table} RENAME COLUMN id_uuid TO id"))
                # Set as primary key
                await db.execute(text(f"ALTER TABLE {table} ADD PRIMARY KEY (id)"))

            # Drop and rename FK columns
            for table, column, _ in fk_columns:
                print(f"Migrating {table}.{column}...")
                await db.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column} CASCADE"))
                await db.execute(text(f"ALTER TABLE {table} RENAME COLUMN {column}_uuid TO {column}"))

            await db.commit()
            print("✓ Old columns dropped and UUID columns renamed\n")

            print("-"*80)
            print("Step 9: Recreate foreign key constraints")
            print("-"*80)
            for table, column, ref_table in fk_columns:
                print(f"Creating FK constraint on {table}.{column}...")
                constraint_name = f"fk_{table}_{column}"
                try:
                    await db.execute(text(f"""
                        ALTER TABLE {table}
                        ADD CONSTRAINT {constraint_name}
                        FOREIGN KEY ({column}) REFERENCES {ref_table}(id)
                    """))
                except Exception as e:
                    print(f"  Warning: Could not create constraint {constraint_name}: {e}")
            await db.commit()
            print("✓ Foreign key constraints recreated\n")

            print("-"*80)
            print("Step 10: Create indexes on UUID columns")
            print("-"*80)
            for table in tables_to_migrate:
                print(f"Creating index on {table}.id...")
                await db.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table}_id ON {table}(id)"))
            await db.commit()
            print("✓ Indexes created\n")

            print("\n" + "="*80)
            print("✅ MIGRATION COMPLETE!")
            print("="*80)
            print("\nNext steps:")
            print("  1. Restart all services to use new UUID models")
            print("  2. All existing dev containers/pods are now invalid")
            print("  3. Users will need to restart their dev environments")
            print("  4. File paths on disk will use new UUIDs")
            print("\n")

        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(migrate())
