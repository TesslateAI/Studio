"""Add startup_command to containers

Revision ID: 0023
Revises: 0022
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_container_start_cmd"
down_revision = "0022_message_updated_at"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent: skip if column already exists (may have been added outside migrations)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'containers' AND column_name = 'startup_command'"
        )
    )
    if not result.fetchone():
        op.add_column("containers", sa.Column("startup_command", sa.String(), nullable=True))


def downgrade():
    op.drop_column("containers", "startup_command")
