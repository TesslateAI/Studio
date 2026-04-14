"""Add skills system with skill_body and agent_skill_assignments

Revision ID: 0024
Revises: 0023
Create Date: 2026-03-12
"""

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op
revision = "0024_add_skills_system"
down_revision = "0023_container_start_cmd"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _column_exists("marketplace_agents", "skill_body"):
        op.add_column("marketplace_agents", sa.Column("skill_body", sa.Text(), nullable=True))

    if not _table_exists("agent_skill_assignments"):
        op.create_table(
            "agent_skill_assignments",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column(
                "agent_id",
                GUID(),
                sa.ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "skill_id",
                GUID(),
                sa.ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                GUID(),
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
