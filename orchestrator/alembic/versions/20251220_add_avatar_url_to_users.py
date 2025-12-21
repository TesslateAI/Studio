"""Add profile columns to users table

Revision ID: 20251220_avatar_url
Revises: 7ff9be407d35
Create Date: 2025-12-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20251220_avatar_url'
down_revision: Union[str, Sequence[str], None] = '7ff9be407d35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add profile columns to users table."""
    # Add columns only if they don't exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('users')]

    if 'avatar_url' not in existing_columns:
        op.add_column('users', sa.Column('avatar_url', sa.String(500), nullable=True))
    if 'bio' not in existing_columns:
        op.add_column('users', sa.Column('bio', sa.Text(), nullable=True))
    if 'twitter_handle' not in existing_columns:
        op.add_column('users', sa.Column('twitter_handle', sa.String(100), nullable=True))
    if 'github_username' not in existing_columns:
        op.add_column('users', sa.Column('github_username', sa.String(100), nullable=True))
    if 'website_url' not in existing_columns:
        op.add_column('users', sa.Column('website_url', sa.String(500), nullable=True))
    if 'referral_code' not in existing_columns:
        op.add_column('users', sa.Column('referral_code', sa.String(), nullable=True))
        op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)
    if 'referred_by' not in existing_columns:
        op.add_column('users', sa.Column('referred_by', sa.String(), nullable=True))
    if 'last_active_at' not in existing_columns:
        op.add_column('users', sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove profile columns from users table."""
    op.drop_column('users', 'last_active_at')
    op.drop_column('users', 'referred_by')
    op.drop_index('ix_users_referral_code', table_name='users')
    op.drop_column('users', 'referral_code')
    op.drop_column('users', 'website_url')
    op.drop_column('users', 'github_username')
    op.drop_column('users', 'twitter_handle')
    op.drop_column('users', 'bio')
    op.drop_column('users', 'avatar_url')
