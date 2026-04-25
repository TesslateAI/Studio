"""Add is_system flag to marketplace_agents.

System agents (e.g. Librarian) are invoked automatically by the platform and
should not appear in user-facing agent selection UIs. The column is set only
via seed code; no Pydantic schema exposes it to users.

Revision ID: 0072_is_system_agent_flag
Revises: 0071_scrub_git_remote_url_tokens
Create Date: 2026-04-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072_is_system_agent_flag"
down_revision: str | Sequence[str] | None = "0071_scrub_git_remote_url_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_agents",
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace_agents", "is_system")
