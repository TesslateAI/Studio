"""Add Project.created_via provenance column.

Revision ID: 0095_project_created_via
Revises: 0094_drop_user_billing_columns
Create Date: 2026-04-29 (renumbered 2026-05-04 to slot above marketplace federation chain)

Distinguishes the origin of a Project row so future cleanup decisions
(stale-empty-workspace GC, template-fork accounting, import vs. fresh
clone) can branch on a single denormalized field instead of pattern-
matching across ``source_path``, ``volume_id``, ``has_git_repo``, etc.

Allowed values: ``template`` | ``empty`` | ``import`` | ``github``.
NULL on rows created before this migration — callers must treat NULL
as "unknown / legacy" and not as one of the discriminators.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0095_project_created_via"
down_revision: str | Sequence[str] | None = "0094_drop_user_billing_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("created_via", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "created_via")
