"""SpendRecord attribution columns for the Automation Runtime.

Revision ID: 0073_spend_record_attribution_columns
Revises: 0072_dedupe_project_files, 0072_is_system_agent_flag
Create Date: 2026-04-26

Phase 0 of the OpenSail Automation Runtime rollout. Adds three nullable
attribution columns to ``spend_records`` so spend rows written between
Phase 0 and Phase 2 carry FK-able pointers from day one:

* ``automation_run_id`` - FK target table ``automation_runs`` is created
  in the Phase 1 alembic, which will add the FK constraint then. Until
  then this column is a plain GUID with no constraint.
* ``invocation_subject_id`` - FK target table ``invocation_subjects`` is
  created in the Phase 2 alembic, which will add the FK constraint then.
  Until then this column is a plain GUID with no constraint.
* ``agent_id`` - FK to ``marketplace_agents.id`` (already exists today)
  with ``ON DELETE SET NULL``. Indexed for per-agent spend rollups.

All three columns are nullable so existing ``spend_records`` rows survive
the migration unchanged (NULL = unattributed).

This revision also acts as a merge for the two parallel 0072 heads
(``0072_dedupe_project_files`` and ``0072_is_system_agent_flag``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0073_spend_record_attribution_columns"
down_revision: str | Sequence[str] | None = (
    "0072_dedupe_project_files",
    "0072_is_system_agent_flag",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table for SQLite compatibility (desktop runtime uses
    # SQLite via aiosqlite; cloud uses PostgreSQL where batch is a no-op
    # wrapper around plain ALTER TABLE).
    #
    # NOTE: FK to automation_runs lands in Phase 1 alembic; FK to
    # invocation_subjects lands in Phase 2 alembic. Only the agent_id
    # FK can be created here because marketplace_agents already exists.
    with op.batch_alter_table("spend_records") as batch_op:
        batch_op.add_column(sa.Column("automation_run_id", GUID(), nullable=True))
        batch_op.add_column(sa.Column("invocation_subject_id", GUID(), nullable=True))
        batch_op.add_column(sa.Column("agent_id", GUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_spend_records_agent_id_marketplace_agents",
            "marketplace_agents",
            ["agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_spend_records_agent_id",
            ["agent_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("spend_records") as batch_op:
        batch_op.drop_index("ix_spend_records_agent_id")
        batch_op.drop_constraint(
            "fk_spend_records_agent_id_marketplace_agents",
            type_="foreignkey",
        )
        batch_op.drop_column("agent_id")
        batch_op.drop_column("invocation_subject_id")
        batch_op.drop_column("automation_run_id")
