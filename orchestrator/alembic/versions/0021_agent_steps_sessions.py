"""Add agent_steps table, chat session fields, and external_api_keys table

Revision ID: 0021_agent_steps_sessions
Revises: 0020_admin_panel_schema
Create Date: 2026-02-25

This migration adds:
- agent_steps table for persisting individual agent tool-call steps
- Chat session metadata columns (title, origin, status, updated_at)
- Composite index on chats (user_id, project_id)
- external_api_keys table for user-managed API key authentication
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0021_agent_steps_sessions"
down_revision = "0020_admin_panel_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()
    existing_chat_columns = [c["name"] for c in inspector.get_columns("chats")]

    # =========================================================================
    # 1. Create agent_steps table
    # =========================================================================
    if "agent_steps" not in existing_tables:
        op.create_table(
            "agent_steps",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
            sa.Column(
                "message_id",
                UUID(as_uuid=True),
                sa.ForeignKey("messages.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("chat_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("step_index", sa.SmallInteger(), nullable=False),
            sa.Column("step_data", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

    # =========================================================================
    # 2. Add session metadata columns to chats table
    # =========================================================================
    if "title" not in existing_chat_columns:
        op.add_column(
            "chats",
            sa.Column("title", sa.String(255), nullable=True),
        )
    if "origin" not in existing_chat_columns:
        op.add_column(
            "chats",
            sa.Column("origin", sa.String(20), nullable=False, server_default="browser"),
        )
    if "status" not in existing_chat_columns:
        op.add_column(
            "chats",
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        )
    if "updated_at" not in existing_chat_columns:
        op.add_column(
            "chats",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    # =========================================================================
    # 3. Add composite index on chats (user_id, project_id)
    # =========================================================================
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("chats")]
    if "ix_chats_user_project" not in existing_indexes:
        op.create_index(
            "ix_chats_user_project",
            "chats",
            ["user_id", "project_id"],
        )

    # =========================================================================
    # 4. Create external_api_keys table
    # =========================================================================
    if "external_api_keys" not in existing_tables:
        op.create_table(
            "external_api_keys",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
            sa.Column("key_prefix", sa.String(12), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("project_ids", sa.JSON(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    # Drop external_api_keys table
    op.drop_table("external_api_keys")

    # Drop composite index on chats
    op.drop_index("ix_chats_user_project", table_name="chats")

    # Remove session metadata columns from chats
    op.drop_column("chats", "updated_at")
    op.drop_column("chats", "status")
    op.drop_column("chats", "origin")
    op.drop_column("chats", "title")

    # Drop agent_steps table
    op.drop_table("agent_steps")
