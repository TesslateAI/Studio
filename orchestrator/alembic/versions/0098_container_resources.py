"""Add containers.resources JSON column for per-container resource overrides.

Revision ID: 0098_container_resources
Revises: 0097_container_source_strategy
Create Date: 2026-05-06

App manifests can now declare per-container resource overrides via
``compute.containers[].resources`` — a free-form dict keyed by
``memory_request`` / ``memory_limit`` / ``cpu_request`` / ``cpu_limit``.
The K8s pod renderer merges these onto the platform defaults
(256Mi req / 1Gi limit / 50m req / 1000m limit) so a heavy app like
crm-demo's prod build (which OOMs at 1Gi) can ask for 2Gi without the
operator hand-editing the deployment after install.

JSON keeps the schema flexible — future contract additions
(e.g. ephemeral-storage, GPU) don't require another migration. NULL
column → defaults apply, identical to legacy installs.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0098_container_resources"
down_revision = "0097_container_source_strategy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "containers",
        sa.Column("resources", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("containers", "resources")
