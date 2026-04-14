"""Add v2 volume-first architecture fields to projects

Adds volume_id, node_name, volume_state, compute_tier, last_sync_at,
and active_compute_pod columns for the v2 volume-first architecture.

Revision ID: 0030_v2_project_fields
Revises: 0029_template_builds
Create Date: 2026-03-14
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0030_v2_project_fields"
down_revision = "0029_template_builds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("volume_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_projects_volume_id", "projects", ["volume_id"])

    op.add_column(
        "projects",
        sa.Column("node_name", sa.String(255), nullable=True),
    )

    op.add_column(
        "projects",
        sa.Column(
            "volume_state",
            sa.String(50),
            nullable=False,
            server_default="legacy",
        ),
    )

    op.add_column(
        "projects",
        sa.Column(
            "compute_tier",
            sa.String(50),
            nullable=False,
            server_default="none",
        ),
    )

    op.add_column(
        "projects",
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "projects",
        sa.Column("active_compute_pod", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "active_compute_pod")
    op.drop_column("projects", "last_sync_at")
    op.drop_column("projects", "compute_tier")
    op.drop_column("projects", "volume_state")
    op.drop_column("projects", "node_name")
    op.drop_index("ix_projects_volume_id", table_name="projects")
    op.drop_column("projects", "volume_id")
