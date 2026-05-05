"""Add containers.source_strategy + containers.state_mount_path.

Revision ID: 0097_container_source_strategy
Revises: 0096_chat_attachments
Create Date: 2026-05-04

The 2026-05 manifest schema lets a Tesslate App container declare two
runtime-shape concerns the orchestrator's pod renderer previously
hard-coded:

  * ``source_strategy`` — whether the runnable code lives in the bundle
    (default; PVC mounts at ``/app``) or in the image (PVC mounts at
    ``state_mount_path`` and the image's WORKDIR / source remain
    authoritative). Image-based seed apps (markitdown, deer-flow,
    mirofish) ship their source in the docker image; mounting the
    bundle PVC at ``/app`` overrides that source. NULL = bundle (legacy
    behaviour).

  * ``state_mount_path`` — where to mount the per-install volume when
    ``source_strategy='image'`` and the manifest declares
    ``state.model='per-install-volume'``. NULL = no extra mount (apps
    that are stateless or whose mount path stays at ``/app`` because
    they're bundle-based).

Both columns are nullable so legacy installs (and bundle-strategy
installs in general) don't need to be backfilled — the renderer
treats NULL ``source_strategy`` as ``'bundle'`` and NULL
``state_mount_path`` as "no extra mount".
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0097_container_source_strategy"
down_revision = "0096_chat_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "containers",
        sa.Column("source_strategy", sa.String(), nullable=True),
    )
    op.add_column(
        "containers",
        sa.Column("state_mount_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("containers", "state_mount_path")
    op.drop_column("containers", "source_strategy")
