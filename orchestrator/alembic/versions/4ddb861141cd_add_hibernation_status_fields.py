"""add_hibernation_status_fields

Revision ID: 4ddb861141cd
Revises: 20251119154619
Create Date: 2025-11-20 23:48:00.938138

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ddb861141cd'
down_revision: Union[str, Sequence[str], None] = '20251119154619'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add hibernation status fields for S3-backed ephemeral storage mode."""
    # Add environment_status column with default value
    op.add_column('projects', sa.Column('environment_status', sa.String(20), server_default='active', nullable=False))

    # Add last_activity column (tracks last user interaction)
    op.add_column('projects', sa.Column('last_activity', sa.DateTime(timezone=True), nullable=True))

    # Add hibernated_at column (tracks when environment was hibernated)
    op.add_column('projects', sa.Column('hibernated_at', sa.DateTime(timezone=True), nullable=True))

    # Add s3_archive_size_bytes column (tracks S3 storage usage for billing)
    op.add_column('projects', sa.Column('s3_archive_size_bytes', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove hibernation status fields."""
    op.drop_column('projects', 's3_archive_size_bytes')
    op.drop_column('projects', 'hibernated_at')
    op.drop_column('projects', 'last_activity')
    op.drop_column('projects', 'environment_status')
