"""Workspace Data Store: collections, records, and data keys.

Revision ID: 0118_workspace_data
Revises: 0117_idle_timeout_two_days
Create Date: 2026-05-21

Adds the built-in per-project KV/document store:
  - workspace_collections : named JSON-document collections per project
  - workspace_records     : individual JSON documents
  - workspace_data_keys   : anon/service API keys for the public Data API

No data migration — all tables are new. Works on Postgres and SQLite
(GUID TypeDecorator + batch-safe table creation).
"""

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision = "0118_workspace_data"
down_revision = "0117_idle_timeout_two_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_collections",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("public_insert", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("public_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_delete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint("project_id", "name", name="uq_workspace_collections_project_name"),
    )
    op.create_index("ix_workspace_collections_project_id", "workspace_collections", ["project_id"])

    op.create_table(
        "workspace_records",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "collection_id",
            GUID(),
            sa.ForeignKey("workspace_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index("ix_workspace_records_collection_id", "workspace_records", ["collection_id"])
    op.create_index("ix_workspace_records_project_id", "workspace_records", ["project_id"])
    op.create_index(
        "ix_workspace_records_collection_created",
        "workspace_records",
        ["collection_id", "created_at"],
    )

    op.create_table(
        "workspace_data_keys",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="anon"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint("key_hash", name="uq_workspace_data_keys_key_hash"),
    )
    op.create_index("ix_workspace_data_keys_project_id", "workspace_data_keys", ["project_id"])


def downgrade() -> None:
    op.drop_table("workspace_data_keys")
    op.drop_table("workspace_records")
    op.drop_table("workspace_collections")
