"""Add deployment_targets and deployment_target_connections tables

Revision ID: 0019_add_deployment_targets
Revises: 0018_add_deployment_provider
Create Date: 2025-01-28

Adds:
- deployment_targets table: Standalone deployment target nodes in the React Flow graph
- deployment_target_connections table: Container-to-deployment-target connections
- deployment_target_id, container_id, version columns to deployments table
"""

from collections.abc import Sequence

import sqlalchemy as sa
from app.types.guid import GUID
from alembic import op
# revision identifiers, used by Alembic.
revision: str = "0019_add_deployment_targets"
down_revision: str | Sequence[str] | None = "0018_add_deployment_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create deployment_targets and deployment_target_connections tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create deployment_targets table
    if "deployment_targets" not in existing_tables:
        op.create_table(
            "deployment_targets",
            sa.Column("id", GUID(), primary_key=True, index=True),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("environment", sa.String(50), default="production"),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("position_x", sa.Float, default=0),
            sa.Column("position_y", sa.Float, default=0),
            sa.Column("is_connected", sa.Boolean, default=False),
            sa.Column(
                "credential_id",
                GUID(),
                sa.ForeignKey("deployment_credentials.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
        )

    # Create deployment_target_connections table
    if "deployment_target_connections" not in existing_tables:
        op.create_table(
            "deployment_target_connections",
            sa.Column("id", GUID(), primary_key=True, index=True),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "container_id",
                GUID(),
                sa.ForeignKey("containers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "deployment_target_id",
                GUID(),
                sa.ForeignKey("deployment_targets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("deployment_settings", sa.JSON, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            # Unique constraint to prevent duplicate connections
            sa.UniqueConstraint(
                "container_id",
                "deployment_target_id",
                name="uq_deployment_target_connection",
            ),
        )

    # Add new columns to deployments table
    existing_deployment_columns = [
        c["name"] for c in inspector.get_columns("deployments")
    ]

    if "deployment_target_id" not in existing_deployment_columns:
        op.add_column(
            "deployments",
            sa.Column("deployment_target_id", GUID(), nullable=True),
        )
        with op.batch_alter_table("deployments") as batch_op:
            batch_op.create_foreign_key(
                "fk_deployments_deployment_target_id",
                "deployment_targets",
                ["deployment_target_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index(
            "ix_deployments_deployment_target_id",
            "deployments",
            ["deployment_target_id"],
        )

    if "container_id" not in existing_deployment_columns:
        op.add_column(
            "deployments",
            sa.Column("container_id", GUID(), nullable=True),
        )
        with op.batch_alter_table("deployments") as batch_op:
            batch_op.create_foreign_key(
                "fk_deployments_container_id",
                "containers",
                ["container_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index(
            "ix_deployments_container_id",
            "deployments",
            ["container_id"],
        )

    if "version" not in existing_deployment_columns:
        op.add_column(
            "deployments",
            sa.Column("version", sa.String(50), nullable=True),
        )


def downgrade() -> None:
    """Remove deployment_targets and deployment_target_connections tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Remove columns from deployments table
    existing_deployment_columns = [
        c["name"] for c in inspector.get_columns("deployments")
    ]

    if "version" in existing_deployment_columns:
        op.drop_column("deployments", "version")

    if "container_id" in existing_deployment_columns:
        op.drop_index("ix_deployments_container_id", table_name="deployments")
        op.drop_column("deployments", "container_id")

    if "deployment_target_id" in existing_deployment_columns:
        op.drop_index("ix_deployments_deployment_target_id", table_name="deployments")
        op.drop_column("deployments", "deployment_target_id")

    # Drop tables
    existing_tables = inspector.get_table_names()

    if "deployment_target_connections" in existing_tables:
        op.drop_table("deployment_target_connections")

    if "deployment_targets" in existing_tables:
        op.drop_table("deployment_targets")
