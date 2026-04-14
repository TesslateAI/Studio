"""Add git_repo_url column to marketplace_agents

Revision ID: 0027_agent_git_repo
Revises: 0026_add_agent_mcp_assignments
Create Date: 2026-03-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0027_agent_git_repo"
down_revision = "0026_add_agent_mcp_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'marketplace_agents' AND column_name = 'git_repo_url'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "marketplace_agents",
            sa.Column("git_repo_url", sa.String(500), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("marketplace_agents", "git_repo_url")
