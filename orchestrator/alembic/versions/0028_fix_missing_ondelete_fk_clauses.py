"""Fix missing ondelete clauses on channel and MCP foreign keys

Migration 0025 omitted ondelete on all foreign keys for channel_configs,
channel_messages, and user_mcp_configs. Without these, deleting a user,
project, or agent that has channel/MCP configuration raises IntegrityError.

Revision ID: 0028_fix_fk_ondelete
Revises: 0027_agent_git_repo
Create Date: 2026-03-13
"""

from alembic import op

# revision identifiers
revision = "0028_fix_fk_ondelete"
down_revision = "0027_agent_git_repo"
branch_labels = None
depends_on = None

# Each tuple: (table, constraint_name, column, referred_table, ondelete)
FK_FIXES = [
    ("channel_configs", "channel_configs_user_id_fkey", "user_id", "users", "CASCADE"),
    ("channel_configs", "channel_configs_project_id_fkey", "project_id", "projects", "SET NULL"),
    ("channel_configs", "channel_configs_default_agent_id_fkey", "default_agent_id", "marketplace_agents", "SET NULL"),
    ("channel_messages", "channel_messages_channel_config_id_fkey", "channel_config_id", "channel_configs", "CASCADE"),
    ("user_mcp_configs", "user_mcp_configs_user_id_fkey", "user_id", "users", "CASCADE"),
    ("user_mcp_configs", "user_mcp_configs_marketplace_agent_id_fkey", "marketplace_agent_id", "marketplace_agents", "SET NULL"),
]


def upgrade() -> None:
    for table, constraint, column, referred, ondelete in FK_FIXES:
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
    for table, constraint, column, referred, _ondelete in FK_FIXES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            referred,
            [column],
            ["id"],
        )
