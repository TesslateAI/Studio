"""Add deployment models

Revision ID: a1b2c3d4e5f6
Revises: 9f5ed32f3379
Create Date: 2025-01-15 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9f5ed32f3379'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add deployment credential and deployment tables."""

    # Create deployment_credentials table
    op.create_table(
        'deployment_credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create indexes for deployment_credentials
    op.create_index('ix_deployment_credentials_id', 'deployment_credentials', ['id'])
    op.create_index('ix_deployment_credentials_user_id', 'deployment_credentials', ['user_id'])
    op.create_index('ix_deployment_credentials_project_id', 'deployment_credentials', ['project_id'])

    # Create unique constraint for user/provider/project combination
    # This allows one default credential per user/provider (project_id = NULL)
    # and one override credential per project/provider (project_id set)
    # PostgreSQL treats NULL values as distinct, so this works as intended
    op.create_unique_constraint(
        'uq_deployment_credentials_user_provider_project',
        'deployment_credentials',
        ['user_id', 'provider', 'project_id']
    )

    # Create deployments table
    op.create_table(
        'deployments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('deployment_id', sa.String(255), nullable=True),
        sa.Column('deployment_url', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('logs', postgresql.JSON(), nullable=True),
        sa.Column('metadata', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Create indexes for deployments
    op.create_index('ix_deployments_id', 'deployments', ['id'])
    op.create_index('ix_deployments_project_id', 'deployments', ['project_id'])
    op.create_index('ix_deployments_user_id', 'deployments', ['user_id'])
    op.create_index('ix_deployments_provider', 'deployments', ['provider'])
    op.create_index('ix_deployments_status', 'deployments', ['status'])
    op.create_index('ix_deployments_created_at', 'deployments', ['created_at'])


def downgrade() -> None:
    """Downgrade schema - remove deployment tables."""

    # Drop tables in reverse order (respect foreign key constraints)
    op.drop_table('deployments')
    op.drop_table('deployment_credentials')
