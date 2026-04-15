"""Add projects.app_role discriminator for Tesslate Apps primitive.

Revision ID: 0053_project_app_role
Revises: 0052_is_builtin_skill
Create Date: 2026-04-14 00:00:00.000000

Context
-------
Tesslate Apps introduces a primitive where a Project can play one of three
roles:
  - 'none'          : ordinary user project (default; existing behavior)
  - 'app_source'    : the authoring Project a creator publishes an AppVersion from
  - 'app_instance'  : a runtime mount of a published AppVersion (created on install)

This migration adds the discriminator column only. The AppInstance table and
the UNIQUE(project_id) constraint enforcing one-Project-one-App live in Wave 2.

Matches the existing codebase convention of String(N) columns + application-
layer enum validation (see Project.environment_status, Project.compute_tier).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0053_project_app_role"
down_revision: str | Sequence[str] | None = "0052_is_builtin_skill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "app_role",
            sa.String(20),
            server_default="none",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_projects_app_role",
        "projects",
        ["app_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_app_role", table_name="projects")
    op.drop_column("projects", "app_role")
