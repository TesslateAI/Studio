"""Add channel and MCP system tables

Revision ID: 0025_channels_mcp
Revises: 0024_add_skills_system
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0025_channels_mcp"
down_revision = "0024_add_skills_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # channel_configs table
    op.create_table(
        "channel_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
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
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_agents.id"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # channel_messages table
    op.create_table(
        "channel_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_config_id",
            UUID(as_uuid=True),
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
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="delivered"
        ),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), index=True
        ),
    )

    # user_mcp_configs table
    op.create_table(
        "user_mcp_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "marketplace_agent_id",
            UUID(as_uuid=True),
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
