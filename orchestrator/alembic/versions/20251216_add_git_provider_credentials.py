"""Add git_provider_credentials table for unified GitHub/GitLab/Bitbucket OAuth

Revision ID: 20251216_gitproviders
Revises: 0768adba32a9
Create Date: 2025-12-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20251216_gitproviders'
down_revision: Union[str, Sequence[str], None] = '0768adba32a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create git_provider_credentials table."""
    op.create_table(
        'git_provider_credentials',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scope', sa.String(length=500), nullable=True),
        sa.Column('provider_username', sa.String(length=255), nullable=False),
        sa.Column('provider_email', sa.String(length=255), nullable=True),
        sa.Column('provider_user_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create index for fast lookups by user_id
    op.create_index('ix_git_provider_credentials_id', 'git_provider_credentials', ['id'], unique=False)

    # Create unique composite index for user_id + provider (one credential per provider per user)
    op.create_index(
        'ix_git_provider_credentials_user_provider',
        'git_provider_credentials',
        ['user_id', 'provider'],
        unique=True
    )


def downgrade() -> None:
    """Drop git_provider_credentials table."""
    op.drop_index('ix_git_provider_credentials_user_provider', table_name='git_provider_credentials')
    op.drop_index('ix_git_provider_credentials_id', table_name='git_provider_credentials')
    op.drop_table('git_provider_credentials')
