"""Schedule trigger extension: non-cron trigger kinds + trigger event queue.

Revision ID: 0059_schedule_triggers
Revises: 0058_approvals_yanks
Create Date: 2026-04-14 00:10:00.000000

Context
-------
Wave 7 extends ``agent_schedules`` beyond cron-only dispatch. New columns:

- ``trigger_kind``      : ``cron | webhook | mcp_event | app_invocation``.
- ``trigger_config``    : JSONB bag for per-kind configuration (e.g. webhook
                          secret, filter expressions).
- ``app_instance_id``   : optional FK binding a schedule to a specific
                          AppInstance (scoped triggers).

A companion ``schedule_trigger_events`` table queues inbound trigger
events. A worker sweeps unprocessed rows (``processed_at IS NULL``) — that
column is indexed with a partial index so the queue scan stays cheap even
when the table grows.

See docs/proposed/plans/tesslate-apps.md §2 (schedule trigger extension).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0059_schedule_triggers"
down_revision: str | Sequence[str] | None = "0058_approvals_yanks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- agent_schedules additive columns -----------------------------------
    _is_sqlite = op.get_bind().dialect.name == "sqlite"
    _app_instance_fk = [] if _is_sqlite else [sa.ForeignKey("app_instances.id", ondelete="CASCADE")]
    op.add_column(
        "agent_schedules",
        sa.Column("trigger_kind", sa.String(16), nullable=False, server_default="cron"),
    )
    op.add_column(
        "agent_schedules",
        sa.Column(
            "trigger_config",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "agent_schedules",
        sa.Column(
            "app_instance_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            *_app_instance_fk,
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_schedules_app_instance_id",
        "agent_schedules",
        ["app_instance_id"],
    )

    # -- schedule_trigger_events --------------------------------------------
    op.create_table(
        "schedule_trigger_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "schedule_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("agent_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_status", sa.String(16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_schedule_trigger_events_schedule_received",
        "schedule_trigger_events",
        ["schedule_id", "received_at"],
    )
    op.create_index(
        "ix_schedule_trigger_events_unprocessed",
        "schedule_trigger_events",
        ["received_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_schedule_trigger_events_unprocessed",
        table_name="schedule_trigger_events",
    )
    op.drop_index(
        "ix_schedule_trigger_events_schedule_received",
        table_name="schedule_trigger_events",
    )
    op.drop_table("schedule_trigger_events")

    op.drop_index(
        "ix_agent_schedules_app_instance_id",
        table_name="agent_schedules",
    )
    op.drop_column("agent_schedules", "app_instance_id")
    op.drop_column("agent_schedules", "trigger_config")
    op.drop_column("agent_schedules", "trigger_kind")
