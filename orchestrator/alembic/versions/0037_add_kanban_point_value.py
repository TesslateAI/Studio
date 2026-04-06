"""Add point_value column to kanban_tasks for story point estimation

Revision ID: 0037_kanban_point_value
Revises: 0036_marketplace_models_team_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_kanban_point_value"
down_revision: str | Sequence[str] | None = "0036_marketplace_models_team_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("kanban_tasks", sa.Column("point_value", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("kanban_tasks", "point_value")
