"""Volume Hub architecture: rename node_name → cache_node, drop volume_state

Drops the 5-state volume_state machine (legacy/provisioning/local/remote_only/
restoring) — the Hub is now the single source of truth.  Renames node_name to
cache_node to clarify it's a disposable hint, not authoritative.

Revision ID: 0031_volume_hub
Revises: 0030_v2_project_fields
"""

revision = "0031_volume_hub"
down_revision = "0030_v2_project_fields"
branch_labels = None
depends_on = None

import sqlalchemy as sa  # noqa: E402
from alembic import op  # noqa: E402


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        # Rename node_name → cache_node (preserves existing data)
        batch_op.alter_column("node_name", new_column_name="cache_node")
        # Drop volume_state — Hub is the source of truth
        batch_op.drop_column("volume_state")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        # Re-add volume_state with default "local" (safe assumption for rollback)
        batch_op.add_column(
            sa.Column(
                "volume_state",
                sa.String(50),
                nullable=False,
                server_default="local",
            )
        )
        # Rename cache_node → node_name
        batch_op.alter_column("cache_node", new_column_name="node_name")
