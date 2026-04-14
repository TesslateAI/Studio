"""Add two-factor authentication

Revision ID: 0008
Revises: 0007
Create Date: 2025-02-09

"""

import sqlalchemy as sa
from alembic import op
from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0008_add_two_factor_auth"
down_revision = "0007_add_base_user_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 2FA columns to users table
    op.add_column("users", sa.Column("two_fa_enabled", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("two_fa_method", sa.String(length=20), nullable=True))

    # Set default value for existing rows
    op.execute("UPDATE users SET two_fa_enabled = false WHERE two_fa_enabled IS NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("two_fa_enabled", nullable=False, server_default=sa.text("false"))

    # Create email_verification_codes table
    op.create_table(
        "email_verification_codes",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_verification_codes_user_id"),
        "email_verification_codes",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_email_verification_codes_user_id"),
        table_name="email_verification_codes",
    )
    op.drop_table("email_verification_codes")
    op.drop_column("users", "two_fa_method")
    op.drop_column("users", "two_fa_enabled")
