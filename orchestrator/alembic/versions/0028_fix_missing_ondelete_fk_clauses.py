"""Fix missing ondelete clauses on channel and MCP foreign keys

Migration 0025 omitted ondelete on all foreign keys for channel_configs,
channel_messages, and user_mcp_configs. Without these, deleting a user,
project, or agent that has channel/MCP configuration raises IntegrityError.

Revision ID: 0028_fix_fk_ondelete
Revises: 0027_agent_git_repo
Create Date: 2026-03-13
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0028_fix_fk_ondelete"
down_revision = "0027_agent_git_repo"
branch_labels = None
depends_on = None

# Each tuple: (table, constraint_name, column, referred_table, ondelete, expected_confdeltype)
# confdeltype: 'a' = NO ACTION, 'r' = RESTRICT, 'c' = CASCADE, 'n' = SET NULL, 'd' = SET DEFAULT
FK_FIXES = [
    ("channel_configs", "channel_configs_user_id_fkey", "user_id", "users", "CASCADE", "c"),
    (
        "channel_configs",
        "channel_configs_project_id_fkey",
        "project_id",
        "projects",
        "SET NULL",
        "n",
    ),
    (
        "channel_configs",
        "channel_configs_default_agent_id_fkey",
        "default_agent_id",
        "marketplace_agents",
        "SET NULL",
        "n",
    ),
    (
        "channel_messages",
        "channel_messages_channel_config_id_fkey",
        "channel_config_id",
        "channel_configs",
        "CASCADE",
        "c",
    ),
    ("user_mcp_configs", "user_mcp_configs_user_id_fkey", "user_id", "users", "CASCADE", "c"),
    (
        "user_mcp_configs",
        "user_mcp_configs_marketplace_agent_id_fkey",
        "marketplace_agent_id",
        "marketplace_agents",
        "SET NULL",
        "n",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for table, constraint, column, referred, ondelete, expected_type in FK_FIXES:
        # Check if FK already has the correct ondelete behavior
        result = conn.execute(
            sa.text("SELECT confdeltype FROM pg_constraint WHERE conname = :name"),
            {"name": constraint},
        )
        row = result.fetchone()
        if row and row[0] == expected_type:
            continue  # Already correct, skip
        if not row:
            # Constraint doesn't exist at all — just create it
            op.create_foreign_key(
                constraint,
                table,
                referred,
                [column],
                ["id"],
                ondelete=ondelete,
            )
        else:
            # Constraint exists but with wrong ondelete — recreate it
            op.drop_constraint(constraint, table, type_="foreignkey")
            op.create_foreign_key(
                constraint,
                table,
                referred,
                [column],
                ["id"],
                ondelete=ondelete,
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, constraint, column, referred, _ondelete, _expected in FK_FIXES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            referred,
            [column],
            ["id"],
        )
