"""Add automation_definitions.compute_profile for the workflow engine.

Revision ID: 0100_automation_compute_profile
Revises: 0099_automation_step_runs
Create Date: 2026-05-07

Phase B of the workflow engine (issue #471). Adds a ``compute_profile``
enum column to ``automation_definitions`` so each workflow can pick the
runner that executes its agent steps:

* ``connector_only`` — runs in a shared, warm agent pool. No PVC, no
  per-project namespace. Tool set restricted at runtime to LLM,
  connectors, app actions, and send_message. Cheap; ~no cold start.
* ``ephemeral_workspace`` — provisions a throwaway PVC + container per
  run. Reserved for Phase B follow-up; today the runner falls back to
  ``persistent_workspace``.
* ``persistent_workspace`` — uses the project's long-lived workspace
  (today's behavior). Default for every existing row.

Defaulting to ``persistent_workspace`` keeps every existing automation's
semantics unchanged. The CHECK constraint is permissive (no Postgres
ENUM ALTER required for future values) and matches the kind enum on
``automation_step_runs``.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0100_automation_compute_profile"
down_revision = "0099_automation_step_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the column + CHECK in a single batch so SQLite test runs work
    # (alembic on SQLite can't ALTER an existing table to add a CHECK
    # constraint without falling back to the copy-and-move strategy
    # batch_alter_table emits). Postgres treats the batch as a normal
    # transaction, so production behaviour is unchanged. Mirrors the
    # pattern in 0103/0104/0105 (also CHECK rewrites on automation_*).
    with op.batch_alter_table("automation_definitions") as batch:
        batch.add_column(
            sa.Column(
                "compute_profile",
                sa.String(32),
                nullable=False,
                server_default="persistent_workspace",
            )
        )
        batch.create_check_constraint(
            "ck_automation_definitions_compute_profile",
            "compute_profile IN ('connector_only', 'ephemeral_workspace', 'persistent_workspace')",
        )


def downgrade() -> None:
    with op.batch_alter_table("automation_definitions") as batch:
        batch.drop_constraint("ck_automation_definitions_compute_profile", type_="check")
        batch.drop_column("compute_profile")
