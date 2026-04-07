"""Add theme_preset to teams for per-team theme switching

Revision ID: 0041_team_theme_preset
Revises: 0040_theme_team_constraint
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_team_theme_preset"
down_revision: str | Sequence[str] | None = "0040_theme_team_constraint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("theme_preset", sa.String(), nullable=True, server_default="default-dark"),
    )
    # Backfill: copy user's theme_preset to their personal team
    op.execute("""
        UPDATE teams SET theme_preset = u.theme_preset
        FROM users u WHERE teams.created_by_id = u.id AND teams.is_personal = true;
    """)


def downgrade() -> None:
    op.drop_column("teams", "theme_preset")
