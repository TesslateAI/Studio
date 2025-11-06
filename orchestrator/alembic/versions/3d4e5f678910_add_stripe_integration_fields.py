"""add_stripe_integration_fields

Revision ID: 3d4e5f678910
Revises: 2c3d4e5f6789
Create Date: 2025-11-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3d4e5f678910'
down_revision: Union[str, Sequence[str], None] = '2c3d4e5f6789'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Add new fields to users table
    op.add_column('users', sa.Column('stripe_subscription_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('deployed_projects_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('creator_stripe_account_id', sa.String(), nullable=True))

    # Add index on stripe_customer_id if not exists
    op.create_index(op.f('ix_users_stripe_customer_id'), 'users', ['stripe_customer_id'], unique=False)

    # Add new fields to projects table
    op.add_column('projects', sa.Column('deploy_type', sa.String(), server_default='development', nullable=False))
    op.add_column('projects', sa.Column('is_deployed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('projects', sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('projects', sa.Column('stripe_payment_intent', sa.String(), nullable=True))

    # Create marketplace_transactions table
    op.create_table('marketplace_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creator_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('transaction_type', sa.String(), nullable=False),
        sa.Column('amount_total', sa.Integer(), nullable=False),
        sa.Column('amount_creator', sa.Integer(), nullable=False),
        sa.Column('amount_platform', sa.Integer(), nullable=False),
        sa.Column('stripe_payment_intent', sa.String(), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(), nullable=True),
        sa.Column('stripe_invoice_id', sa.String(), nullable=True),
        sa.Column('payout_status', sa.String(), server_default='pending', nullable=False),
        sa.Column('payout_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stripe_payout_id', sa.String(), nullable=True),
        sa.Column('tokens_input', sa.Integer(), nullable=True),
        sa.Column('tokens_output', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['marketplace_agents.id'], ),
        sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_marketplace_transactions_id'), 'marketplace_transactions', ['id'], unique=False)

    # Create credit_purchases table
    op.create_table('credit_purchases',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('credits_amount', sa.Integer(), nullable=False),
        sa.Column('stripe_payment_intent', sa.String(), nullable=False),
        sa.Column('stripe_checkout_session', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credit_purchases_id'), 'credit_purchases', ['id'], unique=False)
    op.create_index(op.f('ix_credit_purchases_stripe_payment_intent'), 'credit_purchases', ['stripe_payment_intent'], unique=True)

    # Create usage_logs table
    op.create_table('usage_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('tokens_input', sa.Integer(), nullable=False),
        sa.Column('tokens_output', sa.Integer(), nullable=False),
        sa.Column('cost_input', sa.Integer(), nullable=False),
        sa.Column('cost_output', sa.Integer(), nullable=False),
        sa.Column('cost_total', sa.Integer(), nullable=False),
        sa.Column('creator_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('creator_revenue', sa.Integer(), server_default='0', nullable=False),
        sa.Column('platform_revenue', sa.Integer(), server_default='0', nullable=False),
        sa.Column('billed_status', sa.String(), server_default='pending', nullable=False),
        sa.Column('invoice_id', sa.String(), nullable=True),
        sa.Column('billed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('request_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['marketplace_agents.id'], ),
        sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_logs_id'), 'usage_logs', ['id'], unique=False)
    op.create_index(op.f('ix_usage_logs_created_at'), 'usage_logs', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop usage_logs table
    op.drop_index(op.f('ix_usage_logs_created_at'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_id'), table_name='usage_logs')
    op.drop_table('usage_logs')

    # Drop credit_purchases table
    op.drop_index(op.f('ix_credit_purchases_stripe_payment_intent'), table_name='credit_purchases')
    op.drop_index(op.f('ix_credit_purchases_id'), table_name='credit_purchases')
    op.drop_table('credit_purchases')

    # Drop marketplace_transactions table
    op.drop_index(op.f('ix_marketplace_transactions_id'), table_name='marketplace_transactions')
    op.drop_table('marketplace_transactions')

    # Remove fields from projects table
    op.drop_column('projects', 'stripe_payment_intent')
    op.drop_column('projects', 'deployed_at')
    op.drop_column('projects', 'is_deployed')
    op.drop_column('projects', 'deploy_type')

    # Remove index and fields from users table
    op.drop_index(op.f('ix_users_stripe_customer_id'), table_name='users')
    op.drop_column('users', 'creator_stripe_account_id')
    op.drop_column('users', 'deployed_projects_count')
    op.drop_column('users', 'stripe_subscription_id')
