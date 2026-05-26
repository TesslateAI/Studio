"""Add inbox_items table for the OpenSail web inbox.

Revision ID: 0102_inbox_items
Revises: 0101_automation_run_events
Create Date: 2026-05-07

Phase D of the workflow engine (issue #473). Adds the destination-side
record for ``CommunicationDestination(kind='web_inbox')``: a thin
projection of ``automation_run_events`` of kind ``delivery.sent`` so
the user can read delivered workflow results inside the platform UI.

Status enum: unread | read | archived. Mark-read flips the row;
archive moves it out of the default list. Source columns
(``source_kind``, ``source_run_id``) let the inbox link back to the
run that produced the item.
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0102_inbox_items"
down_revision = "0101_automation_run_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_items",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column(
            "source_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="unread",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('unread', 'read', 'archived')",
            name="ck_inbox_items_status",
        ),
    )
    op.create_index(
        "ix_inbox_items_user_status_created",
        "inbox_items",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_items_user_status_created", table_name="inbox_items")
    op.drop_table("inbox_items")
