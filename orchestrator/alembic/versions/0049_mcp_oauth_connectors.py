"""Add OAuth connector support to MCP (scope tiers + token storage)

Revision ID: 0049_mcp_oauth_connectors
Revises: 0048_project_sync_fields
Create Date: 2026-04-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

revision: str = "0049_mcp_oauth_connectors"
down_revision: str | Sequence[str] | None = "0048_project_sync_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extend user_mcp_configs with scoping + per-tool filter columns
    # ------------------------------------------------------------------
    # Add plain columns first (safe outside batch on all dialects)
    op.add_column(
        "user_mcp_configs",
        sa.Column("scope_level", sa.String(16), nullable=False, server_default="team"),
    )
    op.add_column(
        "user_mcp_configs",
        sa.Column("project_id", GUID(), nullable=True),
    )
    op.add_column(
        "user_mcp_configs",
        sa.Column("disabled_tools", sa.JSON, nullable=True),
    )
    op.add_column(
        "user_mcp_configs",
        sa.Column("parent_config_id", GUID(), nullable=True),
    )

    # Constraint + index operations must use batch mode for SQLite compatibility
    with op.batch_alter_table("user_mcp_configs") as batch_op:
        batch_op.create_foreign_key(
            "fk_user_mcp_configs_project",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_user_mcp_configs_parent",
            "user_mcp_configs",
            ["parent_config_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_user_mcp_configs_scope_project",
            ["scope_level", "project_id"],
        )

    # Backfill: rows without a team_id are personal installs
    op.execute("UPDATE user_mcp_configs SET scope_level = 'user' WHERE team_id IS NULL")

    # ------------------------------------------------------------------
    # 2. New mcp_oauth_connections table (1:1 with user_mcp_configs)
    # ------------------------------------------------------------------
    op.create_table(
        "mcp_oauth_connections",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "user_mcp_config_id",
            GUID(),
            sa.ForeignKey("user_mcp_configs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("server_url", sa.Text, nullable=False),
        sa.Column("tokens_encrypted", sa.Text, nullable=False),
        sa.Column("client_info_encrypted", sa.Text, nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_server_url", sa.Text, nullable=True),
        sa.Column("registration_method", sa.String(32), nullable=False),
        sa.Column("protocol_version", sa.String(16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_connections")
    with op.batch_alter_table("user_mcp_configs") as batch_op:
        batch_op.drop_index("ix_user_mcp_configs_scope_project")
        batch_op.drop_constraint("fk_user_mcp_configs_parent", type_="foreignkey")
        batch_op.drop_constraint("fk_user_mcp_configs_project", type_="foreignkey")
        batch_op.drop_column("parent_config_id")
        batch_op.drop_column("disabled_tools")
        batch_op.drop_column("project_id")
        batch_op.drop_column("scope_level")
