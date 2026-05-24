"""Workspace Data Store: secure-by-default collection flags.

Revision ID: 0119_wsdata_secure_defaults
Revises: 0118_workspace_data
Create Date: 2026-05-24

Lowers the server-default for ``workspace_collections.public_insert`` from
``true`` to ``false``. Aligns the column default with the model and Pydantic
schema, which both moved to closed-by-default in this commit.

Existing rows are intentionally **not** touched — a row with
``public_insert=true`` was an explicit opt-in by some prior caller (UI,
agent, or API) and silently flipping it to false would break live deployed
frontends. Only NEW collections (created after this migration) get the
secure default. Operators wanting to retro-tighten can `UPDATE
workspace_collections SET public_insert = false WHERE ...` themselves.

NB: revision ID must fit ``alembic_version.version_num VARCHAR(32)`` —
the original ``0119_workspace_data_secure_defaults`` was 37 chars and
crashed the migration in beta (StringDataRightTruncation). Keep all
future revision IDs ≤ 32 chars.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0119_wsdata_secure_defaults"
down_revision = "0118_workspace_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``batch_alter_table`` is a no-op rewrap on Postgres and the supported
    # path on SQLite, where direct ALTER COLUMN is partial — keeps both
    # dialects on the same code path.
    with op.batch_alter_table("workspace_collections") as batch_op:
        batch_op.alter_column(
            "public_insert",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )


def downgrade() -> None:
    with op.batch_alter_table("workspace_collections") as batch_op:
        batch_op.alter_column(
            "public_insert",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )
