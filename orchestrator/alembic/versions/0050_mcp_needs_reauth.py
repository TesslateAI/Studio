"""Track when an MCP connector needs re-authorization.

When discovery hits 401/OAuth errors we flag the config so the UI can
surface a "Reconnect" prompt (red dot on the card) and the agent can
warn the user instead of silently dropping tools.

Revision ID: 0050_mcp_needs_reauth
Revises: 0049_mcp_oauth_connectors
Create Date: 2026-04-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_mcp_needs_reauth"
down_revision: str | Sequence[str] | None = "0049_mcp_oauth_connectors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_mcp_configs",
        sa.Column(
            "needs_reauth",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "user_mcp_configs",
        sa.Column("last_auth_error", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_mcp_configs", "last_auth_error")
    op.drop_column("user_mcp_configs", "needs_reauth")
