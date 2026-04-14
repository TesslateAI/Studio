"""Add bundled and purchased credits system

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-26

This migration adds the new credit system:
- bundled_credits: Monthly allowance that resets
- purchased_credits: Never expire
- credits_reset_date: When bundled credits reset

It also migrates existing credits_balance to purchased_credits (since those were all purchased).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0005_billing_credits_system"
down_revision = "0004_add_user_providers_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new credit columns to users table
    op.add_column(
        "users", sa.Column("bundled_credits", sa.Integer(), nullable=False, server_default="1000")
    )
    op.add_column(
        "users", sa.Column("purchased_credits", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "users", sa.Column("credits_reset_date", sa.DateTime(timezone=True), nullable=True)
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    # Migrate existing credits_balance to purchased_credits
    # Existing credits were all purchased (no bundled system before)
    op.execute("""
        UPDATE users
        SET purchased_credits = COALESCE(credits_balance, 0)
        WHERE credits_balance > 0
    """)

    # Set initial bundled credits based on subscription tier
    # free and basic get 1000, pro gets 2500, ultra gets 12000
    op.execute("""
        UPDATE users
        SET bundled_credits = CASE
            WHEN subscription_tier = 'ultra' THEN 12000
            WHEN subscription_tier = 'pro' THEN 2500
            WHEN subscription_tier = 'basic' THEN 1000
            ELSE 1000
        END
    """)

    # Set credits_reset_date for paid subscribers (30 days from now)
    op.execute("""
        UPDATE users
        SET credits_reset_date = NOW() + INTERVAL '30 days'
        WHERE subscription_tier != 'free'
    """)


def downgrade() -> None:
    # Remove the new columns
    op.drop_column("users", "credits_reset_date")
    op.drop_column("users", "purchased_credits")
    op.drop_column("users", "bundled_credits")
