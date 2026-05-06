"""marketplace sources: attestation_pubkey column (Wave 6).

Revision ID: 0090_msrc_pubkey
Revises: 0089_theme_id_uuid
Create Date: 2026-04-29

Wave 6 of the federated-marketplace decoupling. Adds a single nullable
column to ``marketplace_sources``:

    attestation_pubkey TEXT NULL

Stores the ed25519 public key (base64) the orchestrator pins for a
source advertising the ``attestations`` capability. The key is captured
on first successful attestation verification (or set explicitly via the
sources admin endpoint) and used to verify subsequent bundle signatures.

Purely additive — no backfill needed and no constraints touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0090_msrc_pubkey"
down_revision: str | Sequence[str] | None = "0089_theme_id_uuid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("marketplace_sources") as batch:
        batch.add_column(sa.Column("attestation_pubkey", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("marketplace_sources") as batch:
        batch.drop_column("attestation_pubkey")
