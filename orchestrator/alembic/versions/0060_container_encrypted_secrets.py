"""Container encrypted_secrets + needs_restart columns.

Revision ID: 0060_container_encrypted_secrets
Revises: 0059_schedule_triggers
Create Date: 2026-04-14 10:00:00.000000

Context
-------
Adds Fernet-encrypted secret storage to containers so node secrets stop
riding on ``environment_vars`` as base64 blobs. Also adds ``needs_restart``
so secret rotation can flag a container for pickup by the restart path.

Follow-up migrations:
  * 0057_backfill_container_secrets  — data move base64 env → Fernet column.
  * 0058_drop_base64_secret_codec    — safety check + marker for cleanup.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0060_container_encrypted_secrets"
down_revision: str | Sequence[str] | None = "0059_schedule_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "containers",
        sa.Column(
            "encrypted_secrets",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column(
        "containers",
        sa.Column(
            "needs_restart",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("containers", "needs_restart")
    op.drop_column("containers", "encrypted_secrets")
