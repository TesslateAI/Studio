"""Add sync snapshot fields to project_snapshots

Revision ID: 0048_project_sync_fields
Revises: 0047_device_registrations
Create Date: 2026-04-13 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0048_project_sync_fields"
down_revision: str | Sequence[str] | None = "0047_device_registrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_snapshots", sa.Column("sync_manifest", sa.JSON(), nullable=True))
    op.add_column("project_snapshots", sa.Column("sync_blob_key", sa.String(255), nullable=True))
    op.add_column("project_snapshots", sa.Column("sync_size_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("project_snapshots", "sync_size_bytes")
    op.drop_column("project_snapshots", "sync_blob_key")
    op.drop_column("project_snapshots", "sync_manifest")
