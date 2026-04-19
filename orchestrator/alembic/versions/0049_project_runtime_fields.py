"""Add runtime, source_path, sync_enabled fields to projects

Revision ID: 0049_project_runtime_fields
Revises: 0048_project_sync_fields
Create Date: 2026-04-14 00:00:00.000000

Adds three columns to ``projects`` to support the desktop local runtime:

- ``runtime`` VARCHAR(16): per-project orchestrator selector
  (values interpreted app-side: ``"local"`` | ``"docker"`` | ``"k8s"``).
  No CHECK constraint — keeps SQLite + forward-compat happy.
- ``source_path`` VARCHAR(1024): optional host path a desktop user imported
  a project from (for reverse-sync / "reveal in Finder" affordances).
- ``sync_enabled`` BOOLEAN: per-project sync toggle, default False.

SQLite-safe via ``op.batch_alter_table``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0049_project_runtime_fields"
down_revision: str | Sequence[str] | None = "0048_project_sync_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("runtime", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("source_path", sa.String(length=1024), nullable=True))
        batch_op.add_column(
            sa.Column(
                "sync_enabled",
                sa.Boolean(),
                nullable=True,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("sync_enabled")
        batch_op.drop_column("source_path")
        batch_op.drop_column("runtime")
