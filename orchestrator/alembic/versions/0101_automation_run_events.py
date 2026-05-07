"""Add automation_run_events append-only log for the workflow engine.

Revision ID: 0101_automation_run_events
Revises: 0100_automation_compute_profile
Create Date: 2026-05-07

Phase C of the workflow engine (issue #472). One row per state
transition or notable boundary inside a run: step started / finished,
tool called, connector touched, app invoked, approval requested /
resolved, artifact produced, delivery sent, budget consumed, error
raised. Powers the run-history UI, the audit trail, and cost rollup
from a single source of truth.

The table is append-only; rows are never updated. The run UUID +
ordering by ``ts`` is the canonical timeline. ``step_run_id`` is
nullable for run-level events (``run.started``, ``run.finished``)
that don't belong to a particular step.

CHECK constraint on ``kind`` is permissive (string + IN) so future
phases can add kinds without an ENUM ALTER. The list mirrors the
:mod:`app.services.workflows.event_log` constants.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0101_automation_run_events"
down_revision = "0100_automation_compute_profile"
branch_labels = None
depends_on = None


_KIND_VALUES = (
    "run.started",
    "run.finished",
    "step.started",
    "step.finished",
    "tool.called",
    "connector.touched",
    "app.invoked",
    "approval.requested",
    "approval.resolved",
    "artifact.produced",
    "delivery.sent",
    "budget.consumed",
    "error.raised",
)


def upgrade() -> None:
    op.create_table(
        "automation_run_events",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "automation_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_run_id",
            GUID(),
            sa.ForeignKey("automation_step_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in _KIND_VALUES) + ")",
            name="ck_automation_run_events_kind",
        ),
    )
    op.create_index(
        "ix_automation_run_events_run_ts",
        "automation_run_events",
        ["automation_run_id", "ts"],
    )
    op.create_index(
        "ix_automation_run_events_kind",
        "automation_run_events",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_run_events_kind",
        table_name="automation_run_events",
    )
    op.drop_index(
        "ix_automation_run_events_run_ts",
        table_name="automation_run_events",
    )
    op.drop_table("automation_run_events")
