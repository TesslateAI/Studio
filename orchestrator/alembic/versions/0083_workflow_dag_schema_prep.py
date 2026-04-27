"""Workflow / DAG schema prep for automation_actions (Phase 6 reservation).

Revision ID: 0083_workflow_dag
Revises: 0082_automation_grants
Create Date: 2026-04-26

Phase 5 lands schema-only support for branching DAG action graphs so the
Phase 6 dispatcher can read these columns without another migration round.
This migration is intentionally additive — no existing rows mutate, no
execution logic is wired in. See plan section "Workflow / DAG action prep"
for the eventual semantics.

Changes
-------
* ``automation_actions.parent_action_id``: self-FK with ``ON DELETE SET
  NULL`` so deleting a parent action breaks the DAG edge but never
  cascades into orphan dispatch rows.
* ``automation_actions.branch_condition``: nullable JSON column carrying a
  Phase-6 condition expression (e.g. ``{"op": "==", "left": "$status",
  "right": "ok"}``). Unenforced today; the dispatcher reads it when DAG
  execution lands.
* CHECK constraint ``ck_automation_actions_action_type`` is widened to
  also accept ``'workflow.run'`` — the Phase 6 entrypoint that fans out
  to child actions via ``parent_action_id``.
* Index on ``parent_action_id`` so the eventual reverse lookup
  (``SELECT … FROM automation_actions WHERE parent_action_id = :pid``) is
  cheap.

Portability
-----------
SQLite cannot ``ALTER TABLE … DROP CONSTRAINT`` so the CHECK rewrite
runs inside ``op.batch_alter_table`` (which rebuilds the table on SQLite
and emits a plain ``ALTER TABLE`` on Postgres). The new column types use
``JSON`` everywhere — Postgres parity uses ``JSONB`` via SQLAlchemy's
postgresql variant in the ORM model; alembic creates the storage as
plain ``JSON`` for portability with the existing ``automation_actions``
``config`` column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0083_workflow_dag"
down_revision: str | Sequence[str] | None = "0082_automation_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Names — kept as module-level constants so the downgrade can refer to the
# exact same strings without typos.
_TABLE = "automation_actions"
_FK_NAME = "fk_automation_actions_parent_action_id"
_INDEX_NAME = "ix_automation_actions_parent_action_id"
_CHECK_OLD = "action_type IN ('agent.run', 'app.invoke', 'gateway.send')"
_CHECK_NEW = (
    "action_type IN ('agent.run', 'app.invoke', 'gateway.send', 'workflow.run')"
)
_CHECK_NAME = "ck_automation_actions_action_type"


def upgrade() -> None:
    # --- Add the new columns first; both nullable so existing rows survive.
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(sa.Column("parent_action_id", GUID(), nullable=True))
        batch_op.add_column(sa.Column("branch_condition", sa.JSON(), nullable=True))

    # --- Self-referential FK: ON DELETE SET NULL so deleting a parent
    # action breaks the DAG edge instead of cascading.
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.create_foreign_key(
            _FK_NAME,
            _TABLE,
            ["parent_action_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # --- Drop the old CHECK constraint and re-create it with 'workflow.run'.
    # Wrapped in batch_alter_table so SQLite (table-rebuild) and Postgres
    # (in-place ALTER) both work.
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_constraint(_CHECK_NAME, type_="check")
        batch_op.create_check_constraint(_CHECK_NAME, _CHECK_NEW)

    # --- Index for the parent-action reverse lookup the Phase 6 DAG
    # dispatcher will use to enumerate children of a workflow node.
    op.create_index(
        _INDEX_NAME,
        _TABLE,
        ["parent_action_id"],
        unique=False,
    )


def downgrade() -> None:
    # Reverse order. Drop the index, then revert the CHECK, drop FK, then
    # the columns. The downgrade restores the pre-Phase-5 narrow CHECK so
    # any 'workflow.run' rows would block here — intentional, as those rows
    # would orphan the dispatcher's enum logic post-downgrade.
    op.drop_index(_INDEX_NAME, table_name=_TABLE)

    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_constraint(_CHECK_NAME, type_="check")
        batch_op.create_check_constraint(_CHECK_NAME, _CHECK_OLD)

    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.drop_column("branch_condition")
        batch_op.drop_column("parent_action_id")
