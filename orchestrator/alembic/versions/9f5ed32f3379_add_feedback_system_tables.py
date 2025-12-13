"""Add feedback system tables

Revision ID: 9f5ed32f3379
Revises: 3d4e5f678910
Create Date: 2025-11-07 02:49:35.221637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid


# revision identifiers, used by Alembic.
revision: str = '9f5ed32f3379'
down_revision: Union[str, Sequence[str], None] = '3d4e5f678910'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create feedback_posts table
    op.create_table(
        'feedback_posts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('upvote_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_feedback_posts_id', 'feedback_posts', ['id'])
    op.create_index('ix_feedback_posts_upvote_count', 'feedback_posts', ['upvote_count'])
    op.create_index('ix_feedback_posts_created_at', 'feedback_posts', ['created_at'])

    # Create feedback_upvotes table
    op.create_table(
        'feedback_upvotes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('feedback_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feedback_posts.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_feedback_upvotes_id', 'feedback_upvotes', ['id'])
    op.create_index('ix_feedback_upvotes_user_id', 'feedback_upvotes', ['user_id'])
    op.create_index('ix_feedback_upvotes_feedback_id', 'feedback_upvotes', ['feedback_id'])
    # Add unique constraint to prevent duplicate upvotes
    op.create_unique_constraint('uq_feedback_upvotes_user_feedback', 'feedback_upvotes', ['user_id', 'feedback_id'])

    # Create feedback_comments table
    op.create_table(
        'feedback_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('feedback_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feedback_posts.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_feedback_comments_id', 'feedback_comments', ['id'])
    op.create_index('ix_feedback_comments_feedback_id', 'feedback_comments', ['feedback_id'])
    op.create_index('ix_feedback_comments_created_at', 'feedback_comments', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop tables in reverse order (respect foreign key constraints)
    op.drop_table('feedback_comments')
    op.drop_table('feedback_upvotes')
    op.drop_table('feedback_posts')
