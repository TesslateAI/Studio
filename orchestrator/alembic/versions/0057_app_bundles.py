"""Tesslate Apps bundles: AppBundle + AppBundleItem.

Revision ID: 0057_app_bundles
Revises: 0056_wallet_ledger
Create Date: 2026-04-14 00:04:00.000000

Context
-------
Wave 2. Lands the App bundle aggregation surface:

- app_bundles       : collection of AppVersions shipped as a single unit.
- app_bundle_items  : ordered membership of AppVersions in a bundle.

See docs/proposed/plans/tesslate-apps.md §2.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0057_app_bundles"
down_revision: str | Sequence[str] | None = "0056_wallet_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- app_bundles ---------------------------------------------------------
    op.create_table(
        "app_bundles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="draft",
        ),  # draft | approved | yanked
        sa.Column("consolidated_manifest_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_app_bundles_owner_user_id", "app_bundles", ["owner_user_id"])
    op.create_index("ix_app_bundles_status", "app_bundles", ["status"])

    # -- app_bundle_items ----------------------------------------------------
    op.create_table(
        "app_bundle_items",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "bundle_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_bundles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "default_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("bundle_id", "app_version_id", name="uq_bundle_version"),
    )
    op.create_index(
        "ix_app_bundle_items_bundle_order",
        "app_bundle_items",
        ["bundle_id", "order_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_app_bundle_items_bundle_order", table_name="app_bundle_items")
    op.drop_table("app_bundle_items")

    op.drop_index("ix_app_bundles_status", table_name="app_bundles")
    op.drop_index("ix_app_bundles_owner_user_id", table_name="app_bundles")
    op.drop_table("app_bundles")
