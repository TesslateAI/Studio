"""Connector Proxy primitives — call audit + per-install grant rows.

Revision ID: 0077_connector_proxy_calls
Revises: 0076_app_runtime_deployments
Create Date: 2026-04-26

Phase 3 of the OpenSail Automation Runtime rollout — Connector Proxy.

Adds the two tables that back the proxy:

1. ``connector_proxy_calls`` — append-only audit row per upstream call. Lets
   the platform offer "Slack-call activity for this install" without
   instrumenting the app pod. The ``error`` column stores a 500-char prefix
   of the upstream response body when the call returned a non-2xx — the
   proxy is responsible for stripping the bearer token before persisting.
2. ``app_connector_grants`` — the per-install consent + resolved-credential
   pointer (``resolved_ref``) the proxy looks up on every call. Each grant
   pins the manifest's ``exposure`` at install time so a manifest upgrade
   that flips ``proxy → env`` cannot silently retro-actively expose secrets
   — that case requires re-consent.

Why land both here: the audit table FKs back to ``app_connector_grants``
via ``requirement_id`` — they form one logical primitive. The plan
sequences them as Phase 3, this is the first Phase 3 migration.

Down revision is ``0076_app_runtime_deployments`` (also Phase 3) — that
migration creates the runtime-identity table, this one layers the
connector consent + audit on top.

Portable across Postgres (cloud) and SQLite (desktop sidecar) via
``op.batch_alter_table`` for the FK alters that SQLite cannot do in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0077_connector_proxy_calls"
down_revision: str | Sequence[str] | None = "0076_app_runtime_deployments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_col() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON on SQLite — matches the chain convention."""
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # app_connector_grants — per-install resolved credential reference.
    # ------------------------------------------------------------------
    op.create_table(
        "app_connector_grants",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "app_instance_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requirement_id",
            GUID(),
            sa.ForeignKey("app_connector_requirements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # {"kind": "oauth_connection", "id": "<uuid>"} or
        # {"kind": "user_mcp_config",  "id": "<uuid>"} or
        # {"kind": "api_key_secret",   "id": "<uuid>"}
        sa.Column("resolved_ref", _json_col(), nullable=False),
        # Pinned at install time; manifest upgrades that change exposure
        # require re-consent (a new grant row with the new value).
        sa.Column("exposure_at_grant", sa.String(8), nullable=False),
        sa.Column(
            "granted_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "exposure_at_grant IN ('proxy', 'env')",
            name="ck_app_connector_grants_exposure_at_grant",
        ),
    )
    # An install can hold at most one *active* grant per requirement.
    # Partial unique index — Postgres only. SQLite (desktop sidecar) gets
    # a plain non-partial unique on the same columns; revoked rows there
    # require an application-level "soft-delete then re-grant" rather than
    # leaving the old row with `revoked_at IS NOT NULL` alongside the new
    # one. The desktop install path already follows that pattern.
    op.create_index(
        "uq_app_connector_grants_active_per_requirement",
        "app_connector_grants",
        ["app_instance_id", "requirement_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_app_connector_grants_app_instance_id",
        "app_connector_grants",
        ["app_instance_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # connector_proxy_calls — append-only audit log for every proxy call.
    # ------------------------------------------------------------------
    op.create_table(
        "connector_proxy_calls",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "app_instance_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requirement_id",
            GUID(),
            # SET NULL so a yanked requirement row doesn't cascade-delete
            # the audit trail — the audit must outlive the manifest row
            # it references.
            sa.ForeignKey("app_connector_requirements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column(
            "bytes_in", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "bytes_out", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "duration_ms", sa.Integer(), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Truncated upstream body (max 500 chars), only populated for >=400.
        # Token-stripping is the proxy's responsibility — this column is the
        # only place a leak could surface, so the writer scrubs Authorization
        # headers and obvious bearer-token shapes before insert.
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_cpc_app_instance_id_created_at",
        "connector_proxy_calls",
        ["app_instance_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_cpc_connector_id_created_at",
        "connector_proxy_calls",
        ["connector_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cpc_connector_id_created_at",
        table_name="connector_proxy_calls",
    )
    op.drop_index(
        "ix_cpc_app_instance_id_created_at",
        table_name="connector_proxy_calls",
    )
    op.drop_table("connector_proxy_calls")

    op.drop_index(
        "ix_app_connector_grants_app_instance_id",
        table_name="app_connector_grants",
    )
    op.drop_index(
        "uq_app_connector_grants_active_per_requirement",
        table_name="app_connector_grants",
    )
    op.drop_table("app_connector_grants")
