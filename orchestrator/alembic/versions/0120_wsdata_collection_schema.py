"""Workspace Data Store: add optional per-collection JSON Schema.

Revision ID: 0120_wsdata_collection_schema
Revises: 0119_wsdata_secure_defaults
Create Date: 2026-05-24

Adds a nullable ``schema`` JSON column to ``workspace_collections``.
``NULL`` (the default for every existing row + every new row that doesn't
supply one) preserves the v1 behaviour: any well-formed JSON object that
passes the structural guards is accepted. A non-NULL value is validated
as a JSON Schema (Draft 2020-12) at write time, and every subsequent
insert/update is validated against it.

NB: revision ID is 27 chars — well under the ``alembic_version.version_num
VARCHAR(32)`` cap that bit us on 0119's first attempt.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0120_wsdata_collection_schema"
down_revision = "0119_wsdata_secure_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_collections",
        sa.Column("schema", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("workspace_collections") as batch_op:
        batch_op.drop_column("schema")
