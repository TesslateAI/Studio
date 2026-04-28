"""Add AutomationDefinition.app_instance_id so per-app drawers can scope lists.

Revision ID: 0087_automation_app_inst
Revises: 0086_chat_delegated_run_columns
Create Date: 2026-04-27

The app workspace drawer (``AppWorkspacePage``) shows an "Automations" tab
and a "Runs" tab. Both tabs need to filter to the install the user is
viewing — today the API returns every automation visible to the user, and
the runs tab even falls back to "first automation in the unscoped list",
which is wrong as soon as the user has more than one install.

This migration adds a nullable FK so an automation can be tagged with the
``AppInstance`` it belongs to. ``ON DELETE SET NULL`` (not CASCADE) so an
uninstall does NOT silently delete user-authored automations + their runs;
the row simply becomes "unscoped" and surfaces in the global automations
list. That preserves the auditing chain through ``automation_runs`` and
matches the soft-delete behaviour already used elsewhere
(``is_active=False``, ``paused_reason='deleted_by_user'``).

Pre-existing rows are unaffected — the column is nullable and defaults to
NULL, so the global automations list keeps showing them. Per-app lists
filter ``app_instance_id == :id`` and exclude legacy NULLs by design (a
user can re-link via the standard PATCH endpoint).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

revision: str = "0087_automation_app_inst"
down_revision: str | Sequence[str] | None = "0086_chat_delegated_run_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    op.add_column(
        "automation_definitions",
        sa.Column("app_instance_id", GUID(), nullable=True),
    )
    if not is_sqlite:
        op.create_foreign_key(
            "fk_automation_definitions_app_instance",
            "automation_definitions",
            "app_instances",
            ["app_instance_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_automation_definitions_app_instance",
        "automation_definitions",
        ["app_instance_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    op.drop_index(
        "ix_automation_definitions_app_instance",
        table_name="automation_definitions",
    )
    if not is_sqlite:
        op.drop_constraint(
            "fk_automation_definitions_app_instance",
            "automation_definitions",
            type_="foreignkey",
        )
    op.drop_column("automation_definitions", "app_instance_id")
