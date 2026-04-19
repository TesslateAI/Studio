"""Add app_install_attempts ledger for installer saga orphan reaping.

Revision ID: 0065_app_install_attempt
Revises: 0064_container_image
Create Date: 2026-04-15 11:00:00.000000

Installer saga: before Wave 9 the Apps installer called
``hub_client.create_volume_from_bundle`` mid-transaction, then did ~180
lines of DB writes. If the worker died after the Hub call but before
commit, the volume was orphaned on the Hub with no trace — no reaper
could ever find it.

This migration adds an append-only ledger: ``AppInstallAttempt``. After
the Hub call succeeds, the saga inserts a row with
``state='hub_created'`` in an independent session and commits
immediately. If the rest of the install succeeds, the row is updated to
``state='committed'`` and linked to the new ``AppInstance``. If it
fails, the reaper finds the ``hub_created`` row older than the grace
window with no linked ``AppInstance`` and calls
``hub_client.delete_volume`` to free the orphan.

Online-safe: new table, no FK from an existing table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0065_app_install_attempt"
down_revision: str | Sequence[str] | None = "0064_container_image"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_install_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "marketplace_app_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("marketplace_apps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "installer_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("state", sa.String(32), nullable=False, server_default="hub_created"),
        sa.Column("volume_id", sa.String(), nullable=True),
        sa.Column("node_name", sa.String(), nullable=True),
        sa.Column("bundle_hash", sa.String(), nullable=True),
        sa.Column(
            "app_instance_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_instances.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reaped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    # Hot path for the reaper: state='hub_created' AND older than grace window.
    op.create_index(
        "ix_app_install_attempts_state_created_at",
        "app_install_attempts",
        ["state", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_install_attempts_state_created_at",
        table_name="app_install_attempts",
    )
    op.drop_table("app_install_attempts")
