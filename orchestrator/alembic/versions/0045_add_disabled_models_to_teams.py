"""Add disabled_models to teams for per-team model preferences

Revision ID: 0045_team_disabled_models
Revises: 0044_keys_models_team
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_team_disabled_models"
down_revision: str | Sequence[str] | None = "0044_keys_models_team"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("disabled_models", sa.JSON(), nullable=True))
    # Backfill: copy user's disabled_models to their personal team
    op.execute("""
        UPDATE teams SET disabled_models = u.disabled_models
        FROM users u WHERE teams.created_by_id = u.id AND teams.is_personal = true
        AND u.disabled_models IS NOT NULL;
    """)


def downgrade() -> None:
    op.drop_column("teams", "disabled_models")
