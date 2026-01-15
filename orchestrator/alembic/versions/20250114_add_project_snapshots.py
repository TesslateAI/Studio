"""Add project_snapshots table for EBS VolumeSnapshot storage

Revision ID: 20250114_snapshots
Revises: 20251220_avatar_url
Create Date: 2025-01-14

Replaces S3 ZIP-based hibernation with EBS VolumeSnapshots for:
- Near-instant hibernation (< 5 seconds)
- Near-instant restore (< 10 seconds, lazy loading)
- Full volume snapshots (node_modules preserved - no npm install on restore)
- Project versioning (up to 5 snapshots per project for Timeline UI)
- Soft delete support (30-day retention after project deletion)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20250114_snapshots'
down_revision: Union[str, Sequence[str], None] = '20251220_avatar_url'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create project_snapshots table and update projects table."""
    # Create project_snapshots table
    op.create_table(
        'project_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        # Kubernetes VolumeSnapshot references
        sa.Column('snapshot_name', sa.String(255), nullable=False, index=True),
        sa.Column('snapshot_namespace', sa.String(255), nullable=False),
        sa.Column('pvc_name', sa.String(255), nullable=True),
        sa.Column('volume_size_bytes', sa.BigInteger(), nullable=True),

        # Snapshot metadata
        sa.Column('snapshot_type', sa.String(50), nullable=False, server_default='hibernation'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('label', sa.String(255), nullable=True),
        sa.Column('is_latest', sa.Boolean(), nullable=False, server_default='false'),

        # Soft delete support
        sa.Column('is_soft_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('soft_delete_expires_at', sa.DateTime(timezone=True), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Create composite indexes for common queries
    op.create_index(
        'ix_project_snapshots_project_created',
        'project_snapshots',
        ['project_id', 'created_at']
    )
    op.create_index(
        'ix_project_snapshots_soft_delete',
        'project_snapshots',
        ['is_soft_deleted', 'soft_delete_expires_at']
    )

    # Add latest_snapshot_id to projects table
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('projects')]

    if 'latest_snapshot_id' not in existing_columns:
        op.add_column('projects', sa.Column('latest_snapshot_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Remove s3_archive_size_bytes column (S3 hibernation replaced by snapshots)
    if 's3_archive_size_bytes' in existing_columns:
        op.drop_column('projects', 's3_archive_size_bytes')


def downgrade() -> None:
    """Remove project_snapshots table and revert projects table changes."""
    # Add back s3_archive_size_bytes column
    op.add_column('projects', sa.Column('s3_archive_size_bytes', sa.Integer(), nullable=True))

    # Remove latest_snapshot_id from projects table
    op.drop_column('projects', 'latest_snapshot_id')

    # Drop indexes
    op.drop_index('ix_project_snapshots_soft_delete', table_name='project_snapshots')
    op.drop_index('ix_project_snapshots_project_created', table_name='project_snapshots')

    # Drop project_snapshots table
    op.drop_table('project_snapshots')
