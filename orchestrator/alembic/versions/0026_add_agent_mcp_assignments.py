"""Add agent_mcp_assignments table

Revision ID: 0026_add_agent_mcp_assignments
Revises: 0025_channels_mcp
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "0026_add_agent_mcp_assignments"
down_revision = "0025_channels_mcp"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table AND table_schema = 'public'"
        ),
        {"table": table},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("agent_mcp_assignments"):
        op.create_table(
            "agent_mcp_assignments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "mcp_config_id",
                UUID(as_uuid=True),
                sa.ForeignKey("user_mcp_configs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
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
