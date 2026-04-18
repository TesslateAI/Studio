"""Add is_builtin flag to marketplace_agents.

Built-in skills are auto-discovered by the agent skill-discovery service
(no AgentSkillAssignment row needed) and are immutable via user/admin UI
endpoints. The column is written exclusively by ``seeds/skills.py``. No
user-facing Pydantic schema exposes the field.

Revision ID: 0052_is_builtin_skill
Revises: 0051_mcp_config_unique_scope
Create Date: 2026-04-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_is_builtin_skill"
down_revision: str | Sequence[str] | None = "0051_mcp_config_unique_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_agents",
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace_agents", "is_builtin")
