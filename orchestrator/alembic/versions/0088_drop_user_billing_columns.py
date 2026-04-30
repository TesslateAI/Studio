"""Drop deprecated billing and deployment-count columns from the users table.

Revision ID: 0088
Revises: 0087_automation_app_inst
Create Date: 2026-04-29

Billing has been team-scoped since migration 0035_rbac_teams, which copied
all billing fields from User to Team.  The per-user columns became dead code
at that point.  deployed_projects_count was similarly duplicated onto Team
but still written to on the User; it is now tracked exclusively on Team.

Columns removed
---------------
subscription_tier, stripe_customer_id, stripe_subscription_id,
total_spend, bundled_credits, purchased_credits, credits_reset_date,
signup_bonus_credits, signup_bonus_expires_at, daily_credits,
daily_credits_reset_date, support_tier, deployed_projects_count

All live billing/deployment data is on the ``teams`` table.  A downgrade
re-adds the columns as nullable so the schema rolls back cleanly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088"
down_revision: str | Sequence[str] | None = "0087_automation_app_inst"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the index that references stripe_customer_id before the batch alter;
    # SQLite batch mode recreates all indexes from the reflected schema and would
    # otherwise try to CREATE the index after the column is gone.
    op.drop_index("ix_users_stripe_customer_id", table_name="users", if_exists=True)
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("subscription_tier")
        batch_op.drop_column("stripe_customer_id")
        batch_op.drop_column("stripe_subscription_id")
        batch_op.drop_column("total_spend")
        batch_op.drop_column("bundled_credits")
        batch_op.drop_column("purchased_credits")
        batch_op.drop_column("credits_reset_date")
        batch_op.drop_column("signup_bonus_credits")
        batch_op.drop_column("signup_bonus_expires_at")
        batch_op.drop_column("daily_credits")
        batch_op.drop_column("daily_credits_reset_date")
        batch_op.drop_column("support_tier")
        batch_op.drop_column("deployed_projects_count")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "subscription_tier",
                sa.String(),
                nullable=True,
                server_default="free",
            )
        )
        batch_op.add_column(sa.Column("stripe_customer_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("stripe_subscription_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("total_spend", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("bundled_credits", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("purchased_credits", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("credits_reset_date", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("signup_bonus_credits", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("signup_bonus_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("daily_credits", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("daily_credits_reset_date", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "support_tier",
                sa.String(length=20),
                nullable=True,
                server_default="community",
            )
        )
        batch_op.add_column(
            sa.Column("deployed_projects_count", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"], unique=False)
