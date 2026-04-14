"""Add agent_mcp_assignments table

Revision ID: 0026_add_agent_mcp_assignments
Revises: 0025_channels_mcp
Create Date: 2026-03-12
"""

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op
# revision identifiers
revision = "0026_add_agent_mcp_assignments"
down_revision = "0025_channels_mcp"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("agent_mcp_assignments"):
        op.create_table(
            "agent_mcp_assignments",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column(
                "agent_id",
                GUID(),
                sa.ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "mcp_config_id",
                GUID(),
                sa.ForeignKey("user_mcp_configs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                GUID(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
            sa.Column(
                "added_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("agent_id", "mcp_config_id", "user_id"),
        )
        op.create_index("ix_agent_mcp_assignments_id", "agent_mcp_assignments", ["id"])


def downgrade() -> None:
    op.drop_index("ix_agent_mcp_assignments_id", table_name="agent_mcp_assignments")
    op.drop_table("agent_mcp_assignments")
