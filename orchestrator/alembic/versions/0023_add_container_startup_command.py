"""Add startup_command to containers

Revision ID: 0023
Revises: 0022
Create Date: 2026-03-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_container_start_cmd"
down_revision = "0022_message_updated_at"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: skip if column already exists (may have been added outside migrations)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("containers")}
    if "startup_command" not in existing:
        op.add_column("containers", sa.Column("startup_command", sa.String(), nullable=True))


def downgrade():
    op.drop_column("containers", "startup_command")
