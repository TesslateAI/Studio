"""Add device_registrations for desktop pairing

Revision ID: 0047_device_registrations
Revises: 0046_merge_heads
Create Date: 2026-04-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0047_device_registrations"
down_revision: str | Sequence[str] | None = "0046_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_api_keys.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("device_name", sa.String(200), nullable=False),
        sa.Column("device_platform", sa.String(40), nullable=True),
        sa.Column("device_fingerprint", sa.String(128), nullable=True),
        sa.Column("app_version", sa.String(40), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_device_registrations_user_id",
        "device_registrations",
        ["user_id"],
    )
    op.create_index(
        "ix_device_registrations_fingerprint",
        "device_registrations",
        ["device_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_device_registrations_fingerprint", table_name="device_registrations")
    op.drop_index("ix_device_registrations_user_id", table_name="device_registrations")
    op.drop_table("device_registrations")
