"""Add team_id to marketplace ownership models

Revision ID: 0037_marketplace_models_team_id
Revises: 0036_marketplace_team_id
"""

revision = "0037_marketplace_models_team_id"
down_revision = "0036_marketplace_team_id"
branch_labels = None
depends_on = None

import sqlalchemy as sa  # noqa: E402
from app.types.guid import GUID
from alembic import op  # noqa: E402

_TABLES = [
    "user_purchased_agents",
    "agent_skill_assignments",
    "user_purchased_bases",
    "user_library_themes",
    "user_mcp_configs",
    "agent_mcp_assignments",
]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("team_id", GUID(), nullable=True))
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table}_team_id", "teams", ["team_id"], ["id"], ondelete="SET NULL"
            )
        op.create_index(f"ix_{table}_team_id", table, ["team_id"])

    if op.get_bind().dialect.name != "postgresql":
        return

    # Backfill: set team_id = user.default_team_id for existing rows
    op.execute("""
        UPDATE user_purchased_agents SET team_id = u.default_team_id
        FROM users u WHERE user_purchased_agents.user_id = u.id AND user_purchased_agents.team_id IS NULL;
    """)
    op.execute("""
        UPDATE agent_skill_assignments SET team_id = u.default_team_id
        FROM users u WHERE agent_skill_assignments.user_id = u.id AND agent_skill_assignments.team_id IS NULL;
    """)
    op.execute("""
        UPDATE user_purchased_bases SET team_id = u.default_team_id
        FROM users u WHERE user_purchased_bases.user_id = u.id AND user_purchased_bases.team_id IS NULL;
    """)
    op.execute("""
        UPDATE user_library_themes SET team_id = u.default_team_id
        FROM users u WHERE user_library_themes.user_id = u.id AND user_library_themes.team_id IS NULL;
    """)
    op.execute("""
        UPDATE user_mcp_configs SET team_id = u.default_team_id
        FROM users u WHERE user_mcp_configs.user_id = u.id AND user_mcp_configs.team_id IS NULL;
    """)
    op.execute("""
        UPDATE agent_mcp_assignments SET team_id = u.default_team_id
        FROM users u WHERE agent_mcp_assignments.user_id = u.id AND agent_mcp_assignments.team_id IS NULL;
    """)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_team_id", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_team_id", type_="foreignkey")
        op.drop_column(table, "team_id")
