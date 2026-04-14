"""Add channel and MCP system tables

Revision ID: 0025_channels_mcp
Revises: 0024_add_skills_system
Create Date: 2026-03-12
"""

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op
# revision identifiers
revision = "0025_channels_mcp"
down_revision = "0024_add_skills_system"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("channel_configs"):
        op.create_table(
            "channel_configs",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column(
                "user_id",
                GUID(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("projects.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("channel_type", sa.String(20), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("credentials", sa.Text, nullable=False),
            sa.Column("webhook_secret", sa.String(64), nullable=False),
            sa.Column(
                "default_agent_id",
                GUID(),
                sa.ForeignKey("marketplace_agents.id"),
                nullable=True,
            ),
            sa.Column("is_active", sa.Boolean, default=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        )

    if not _table_exists("channel_messages"):
        op.create_table(
            "channel_messages",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column(
                "channel_config_id",
                GUID(),
                sa.ForeignKey("channel_configs.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("direction", sa.String(10), nullable=False),
            sa.Column("jid", sa.String(255), nullable=False),
            sa.Column("sender_name", sa.String(100), nullable=True),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("platform_message_id", sa.String(255), nullable=True),
            sa.Column("task_id", sa.String, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="delivered"),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), index=True),
        )

    if not _table_exists("user_mcp_configs"):
        op.create_table(
            "user_mcp_configs",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column(
                "user_id",
                GUID(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "marketplace_agent_id",
                GUID(),
                sa.ForeignKey("marketplace_agents.id"),
                nullable=False,
            ),
            sa.Column("credentials", sa.Text, nullable=True),
            sa.Column("enabled_capabilities", sa.JSON, nullable=True),
            sa.Column("is_active", sa.Boolean, default=True),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("user_mcp_configs")
    op.drop_table("channel_messages")
    op.drop_table("channel_configs")
