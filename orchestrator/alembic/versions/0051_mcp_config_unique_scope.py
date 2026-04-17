"""Add partial unique index on UserMcpConfig scope tuple.

Prevents duplicate connector installs for the same (user, agent, scope,
team, project) combination — previously enforced only at the application
level via SELECT-then-INSERT, which was susceptible to race conditions.

Revision ID: 0051_mcp_config_unique_scope
Revises: 0050_mcp_needs_reauth
Create Date: 2026-04-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_mcp_config_unique_scope"
down_revision: str | Sequence[str] | None = "0050_mcp_needs_reauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_user_mcp_configs_scope"


def upgrade() -> None:
    # Partial unique index — only enforced on active, catalog-backed rows.
    # Custom connectors (marketplace_agent_id IS NULL) are excluded because
    # multiple BYO servers at the same URL can legitimately coexist.
    # postgresql_where is ignored on SQLite (no partial-index support), which
    # is acceptable — the desktop sidecar has low concurrency so race conditions
    # are theoretical.
    op.create_index(
        _INDEX_NAME,
        "user_mcp_configs",
        [
            "user_id",
            "marketplace_agent_id",
            "scope_level",
            sa.text("COALESCE(team_id, '00000000-0000-0000-0000-000000000000')"),
            sa.text("COALESCE(project_id, '00000000-0000-0000-0000-000000000000')"),
        ],
        unique=True,
        postgresql_where=sa.text("marketplace_agent_id IS NOT NULL AND is_active = true"),
    )

    # Fix the server_default mismatch from 0049.
    # op.alter_column generates ALTER COLUMN which SQLite doesn't support —
    # use batch_alter_table (copy-and-move) so it works on both dialects.
    with op.batch_alter_table("user_mcp_configs") as batch_op:
        batch_op.alter_column("scope_level", server_default="user")


def downgrade() -> None:
    with op.batch_alter_table("user_mcp_configs") as batch_op:
        batch_op.alter_column("scope_level", server_default="team")
    op.drop_index(_INDEX_NAME, table_name="user_mcp_configs")
