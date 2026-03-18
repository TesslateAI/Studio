"""Add skills system with skill_body and agent_skill_assignments

Revision ID: 0024
Revises: 0023
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0024_add_skills_system"
down_revision = "0023_container_start_cmd"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


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


def upgrade():
    if not _column_exists("marketplace_agents", "skill_body"):
        op.add_column("marketplace_agents", sa.Column("skill_body", sa.Text(), nullable=True))

    if not _table_exists("agent_skill_assignments"):
        op.create_table(
            "agent_skill_assignments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "skill_id",
                UUID(as_uuid=True),
                sa.ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
            sa.Column(
                "added_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint("agent_id", "skill_id", "user_id", name="uq_agent_skill_user"),
        )


def downgrade():
    op.drop_table("agent_skill_assignments")
    op.drop_column("marketplace_agents", "skill_body")
