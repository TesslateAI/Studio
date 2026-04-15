"""Tesslate Apps core hub entities: marketplace_apps, app_versions, app_instances, mcp_consent_records.

Revision ID: 0055_apps_core
Revises: 0054_litellm_key_ledger
Create Date: 2026-04-14 00:02:00.000000

Context
-------
Wave 1 of the Tesslate Apps infrastructure. Lands the core hub entity tables:

- marketplace_apps  : the "App" hub object (slug, creator, forkability, state).
- app_versions      : IMMUTABLE per-version manifest snapshots (hashes, approval,
                      yanking with two-admin rule on critical yanks).
- app_instances     : per-install leaf. One installed App per Project enforced
                      via partial unique index.
- mcp_consent_records: per-install scoped MCP consent grants.

See docs/proposed/plans/tesslate-apps.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0055_apps_core"
down_revision: str | Sequence[str] | None = "0054_litellm_key_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- marketplace_apps ----------------------------------------------------
    op.create_table(
        "marketplace_apps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "creator_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("icon_ref", sa.Text(), nullable=True),
        sa.Column(
            "forkable",
            sa.String(16),
            nullable=False,
            server_default="restricted",
        ),  # true | restricted | no
        sa.Column(
            "forked_from",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marketplace_apps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "visibility",
            sa.String(32),
            nullable=False,
            server_default="private",
        ),  # public | private | team:<uuid>
        sa.Column(
            "state",
            sa.String(24),
            nullable=False,
            server_default="draft",
        ),  # draft | pending_stage1 | pending_stage2 | approved | deprecated | yanked
        sa.Column(
            "reputation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
    op.create_index("ix_marketplace_apps_creator_user_id", "marketplace_apps", ["creator_user_id"])
    op.create_index("ix_marketplace_apps_state", "marketplace_apps", ["state"])
    op.create_index("ix_marketplace_apps_category", "marketplace_apps", ["category"])
    op.create_index("ix_marketplace_apps_forked_from", "marketplace_apps", ["forked_from"])

    # -- app_versions --------------------------------------------------------
    op.create_table(
        "app_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marketplace_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("manifest_schema_version", sa.String(16), nullable=False),
        sa.Column(
            "manifest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("bundle_hash", sa.Text(), nullable=True),
        sa.Column("feature_set_hash", sa.Text(), nullable=False),
        sa.Column(
            "required_features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "approval_state",
            sa.String(24),
            nullable=False,
            server_default="pending_stage1",
        ),  # pending_stage1 | stage1_approved | pending_stage2 | stage2_approved | rejected | yanked
        sa.Column(
            "approval_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("yanked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yanked_reason", sa.Text(), nullable=True),
        sa.Column(
            "yanked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "yanked_is_critical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "yanked_second_admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("app_id", "version", name="uq_app_version_app_slug"),
        sa.CheckConstraint(
            "NOT (yanked_is_critical AND yanked_at IS NOT NULL AND yanked_second_admin_id IS NULL)",
            name="ck_app_version_critical_two_admin",
        ),
    )
    op.create_index("ix_app_versions_app_id_version", "app_versions", ["app_id", "version"])
    op.create_index("ix_app_versions_approval_state", "app_versions", ["approval_state"])
    op.create_index("ix_app_versions_bundle_hash", "app_versions", ["bundle_hash"])

    # -- app_instances -------------------------------------------------------
    op.create_table(
        "app_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marketplace_apps.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "installer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "state",
            sa.String(24),
            nullable=False,
            server_default="installing",
        ),  # installing | installed | upgrading | uninstalled | error
        sa.Column(
            "consent_record",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "wallet_mix",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "update_policy",
            sa.String(16),
            nullable=False,
            server_default="manual",
        ),  # manual | patch-auto | minor-auto | pinned
        sa.Column("volume_id", sa.Text(), nullable=True),
        sa.Column("feature_set_hash", sa.Text(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "uq_app_instance_project_installed",
        "app_instances",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("state = 'installed' AND project_id IS NOT NULL"),
    )
    op.create_index(
        "ix_app_instances_installer_state",
        "app_instances",
        ["installer_user_id", "state"],
    )
    op.create_index("ix_app_instances_app_version_id", "app_instances", ["app_version_id"])
    op.create_index("ix_app_instances_app_id", "app_instances", ["app_id"])

    # -- mcp_consent_records -------------------------------------------------
    op.create_table(
        "mcp_consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "app_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mcp_server_id", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_mcp_consent_records_app_instance_id",
        "mcp_consent_records",
        ["app_instance_id"],
    )
    op.create_index(
        "ix_mcp_consent_records_mcp_server_id",
        "mcp_consent_records",
        ["mcp_server_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_consent_records_mcp_server_id", table_name="mcp_consent_records")
    op.drop_index("ix_mcp_consent_records_app_instance_id", table_name="mcp_consent_records")
    op.drop_table("mcp_consent_records")

    op.drop_index("ix_app_instances_app_id", table_name="app_instances")
    op.drop_index("ix_app_instances_app_version_id", table_name="app_instances")
    op.drop_index("ix_app_instances_installer_state", table_name="app_instances")
    op.drop_index("uq_app_instance_project_installed", table_name="app_instances")
    op.drop_table("app_instances")

    op.drop_index("ix_app_versions_bundle_hash", table_name="app_versions")
    op.drop_index("ix_app_versions_approval_state", table_name="app_versions")
    op.drop_index("ix_app_versions_app_id_version", table_name="app_versions")
    op.drop_table("app_versions")

    op.drop_index("ix_marketplace_apps_forked_from", table_name="marketplace_apps")
    op.drop_index("ix_marketplace_apps_category", table_name="marketplace_apps")
    op.drop_index("ix_marketplace_apps_state", table_name="marketplace_apps")
    op.drop_index("ix_marketplace_apps_creator_user_id", table_name="marketplace_apps")
    op.drop_table("marketplace_apps")
