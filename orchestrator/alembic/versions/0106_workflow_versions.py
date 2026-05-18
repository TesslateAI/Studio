"""Add workflow_versions immutable snapshots + pointers (G1, issue #469).

Revision ID: 0106_workflow_versions
Revises: 0105_dag_action_kinds
Create Date: 2026-05-11

G1 of the self-evolving workflow agent track. Every change to an
``AutomationDefinition``'s contract, actions, triggers, or
delivery_targets writes a row to ``workflow_versions`` carrying an
immutable snapshot of the whole shape. ``head_version_id`` is the
live pointer; runs stamp ``workflow_version_id`` so we can:

* roll back by flipping the pointer,
* diff the JSON to see what changed,
* attribute a failure to a specific version (and to whoever / which
  agent run wrote it).

Schema notes:

* ``payload_sha256`` lets us dedupe identical writes (an idempotent
  PATCH should not multiply rows).
* ``created_by_run_id`` is non-null exactly when an agent run wrote
  the version; ``created_by_user_id`` is non-null when a human did.
  Both null means a system bootstrap (the lazy first version).
* The two FK columns on existing tables (``automation_definitions.head_version_id``,
  ``automation_runs.workflow_version_id``) are NULLABLE in this
  migration. A backfill sweep (run separately) lazily creates a
  generation-1 version for each existing definition, then a follow-up
  migration can promote both columns to NOT NULL.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0106_workflow_versions"
down_revision = "0105_dag_action_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "automation_id",
            GUID(),
            sa.ForeignKey("automation_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "parent_version_id",
            GUID(),
            sa.ForeignKey("workflow_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "automation_id",
            "payload_sha256",
            name="uq_workflow_versions_automation_sha",
        ),
    )
    op.create_index(
        "ix_workflow_versions_automation_generation",
        "workflow_versions",
        ["automation_id", sa.text("generation DESC")],
    )

    # Live-pointer columns on the definition + per-run reference. Wrapped
    # in batch_alter_table because SQLite (desktop sidecar + CI test DB)
    # can't ALTER TABLE ADD a column with a FOREIGN KEY constraint
    # without falling back to the copy-and-move strategy.
    # batch_alter_table on SQLite rebuilds the table via copy-and-move
    # and requires every constraint on the new column to have an
    # explicit name (alembic raises ``Constraint must have a name``
    # otherwise). Postgres ignores the name, so naming is free here.
    with op.batch_alter_table("automation_definitions") as batch:
        batch.add_column(
            sa.Column(
                "head_version_id",
                GUID(),
                sa.ForeignKey(
                    "workflow_versions.id",
                    name="fk_automation_definitions_head_version_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
    with op.batch_alter_table("automation_runs") as batch:
        batch.add_column(
            sa.Column(
                "workflow_version_id",
                GUID(),
                sa.ForeignKey(
                    "workflow_versions.id",
                    name="fk_automation_runs_workflow_version_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("automation_runs") as batch:
        batch.drop_column("workflow_version_id")
    with op.batch_alter_table("automation_definitions") as batch:
        batch.drop_column("head_version_id")
    op.drop_index(
        "ix_workflow_versions_automation_generation",
        table_name="workflow_versions",
    )
    op.drop_table("workflow_versions")
