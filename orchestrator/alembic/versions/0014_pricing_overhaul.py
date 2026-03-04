"""Add pricing overhaul columns: signup bonus, daily credits, support tier

Revision ID: 0014
Revises: 0013_add_key_base_url
Create Date: 2026-02-22

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_pricing_overhaul"
down_revision = "0013_add_key_base_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("signup_bonus_credits", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("signup_bonus_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("daily_credits", sa.Integer(), nullable=False, server_default="0"),
    )
    # daily_credits_reset_date is nullable — existing users will have NULL.
    # The daily_credit_reset background loop handles NULL via an IS NULL clause,
    # so existing free-tier users will get their daily credits on the next hourly run.
    op.add_column(
        "users",
        sa.Column("daily_credits_reset_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("support_tier", sa.String(20), nullable=False, server_default="community"),
    )


def downgrade() -> None:
    op.drop_column("users", "support_tier")
    op.drop_column("users", "daily_credits_reset_date")
    op.drop_column("users", "daily_credits")
    op.drop_column("users", "signup_bonus_expires_at")
    op.drop_column("users", "signup_bonus_credits")
