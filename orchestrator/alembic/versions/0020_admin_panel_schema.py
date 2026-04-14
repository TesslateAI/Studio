"""Add admin panel schema (user management, health checks, audit logs)

Revision ID: 0020_admin_panel_schema
Revises: 0019_add_deployment_targets
Create Date: 2026-01-29

This migration adds:
- User suspension fields (is_suspended, suspended_at, suspended_reason, suspended_by_id)
- User soft-delete fields (is_deleted, deleted_at, deleted_reason, deleted_by_id, scheduled_hard_delete_at)
- health_checks table for system monitoring
- admin_actions table for audit logging
"""

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op
# revision identifiers
revision = "0020_admin_panel_schema"
down_revision = "0019_add_deployment_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()
    existing_user_columns = [c["name"] for c in inspector.get_columns("users")]

    # =========================================================================
    # 1. Add suspension fields to users table
    # =========================================================================
    if "is_suspended" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default="false"),
        )
    if "suspended_at" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "suspended_reason" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("suspended_reason", sa.Text(), nullable=True),
        )
    if "suspended_by_id" not in existing_user_columns:
        op.add_column("users", sa.Column("suspended_by_id", GUID(), nullable=True))
        with op.batch_alter_table("users") as batch_op:
            batch_op.create_foreign_key(
                "fk_users_suspended_by_id", "users", ["suspended_by_id"], ["id"], ondelete="SET NULL"
            )

    # =========================================================================
    # 2. Add soft-delete fields to users table
    # =========================================================================
    if "is_deleted" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        )
    if "deleted_at" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "deleted_reason" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("deleted_reason", sa.Text(), nullable=True),
        )
    if "deleted_by_id" not in existing_user_columns:
        op.add_column("users", sa.Column("deleted_by_id", GUID(), nullable=True))
        with op.batch_alter_table("users") as batch_op:
            batch_op.create_foreign_key(
                "fk_users_deleted_by_id", "users", ["deleted_by_id"], ["id"], ondelete="SET NULL"
            )
    if "scheduled_hard_delete_at" not in existing_user_columns:
        op.add_column(
            "users",
            sa.Column("scheduled_hard_delete_at", sa.DateTime(timezone=True), nullable=True),
        )

    # =========================================================================
    # 3. Create health_checks table
    # =========================================================================
    if "health_checks" not in existing_tables:
        op.create_table(
            "health_checks",
            sa.Column("id", GUID(), primary_key=True, index=True),
            sa.Column("service_name", sa.String(50), nullable=False, index=True),
            sa.Column("status", sa.String(20), nullable=False),  # up, down, degraded
            sa.Column("response_time_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("extra_data", sa.JSON(), server_default="{}"),
            sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        )

        # Create composite index for efficient queries
        op.create_index(
            "idx_health_checks_service_time",
            "health_checks",
            ["service_name", "checked_at"],
        )

    # =========================================================================
    # 4. Create admin_actions table
    # =========================================================================
    if "admin_actions" not in existing_tables:
        op.create_table(
            "admin_actions",
            sa.Column("id", GUID(), primary_key=True, index=True),
            sa.Column(
                "admin_id",
                GUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("action_type", sa.String(100), nullable=False, index=True),
            sa.Column("target_type", sa.String(50), nullable=False),  # user, project, agent, etc.
            sa.Column("target_id", GUID(), nullable=False, index=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("extra_data", sa.JSON(), server_default="{}"),
            sa.Column("ip_address", sa.String(45), nullable=True),  # IPv4 or IPv6
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        )

        # Create composite index for efficient target lookups
        op.create_index(
            "idx_admin_actions_target",
            "admin_actions",
            ["target_type", "target_id"],
        )


def downgrade() -> None:
    # Drop admin_actions table and indexes
    op.drop_index("idx_admin_actions_target", table_name="admin_actions")
    op.drop_table("admin_actions")

    # Drop health_checks table and indexes
    op.drop_index("idx_health_checks_service_time", table_name="health_checks")
    op.drop_table("health_checks")

    # Remove soft-delete columns from users
    op.drop_column("users", "scheduled_hard_delete_at")
    op.drop_column("users", "deleted_by_id")
    op.drop_column("users", "deleted_reason")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "is_deleted")

    # Remove suspension columns from users
    op.drop_column("users", "suspended_by_id")
    op.drop_column("users", "suspended_reason")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "is_suspended")
