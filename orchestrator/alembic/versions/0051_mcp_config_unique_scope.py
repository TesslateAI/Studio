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

    # Also fix the server_default mismatch from 0049 (M3 from review).
    op.alter_column(
        "user_mcp_configs",
        "scope_level",
        server_default="user",
    )


def downgrade() -> None:
    op.alter_column(
        "user_mcp_configs",
        "scope_level",
        server_default="team",
    )
    op.drop_index(_INDEX_NAME, table_name="user_mcp_configs")
