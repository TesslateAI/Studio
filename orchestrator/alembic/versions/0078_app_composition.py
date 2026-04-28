"""App Composition primitives — install-time link wiring + saved view embeds.

Revision ID: 0078_app_composition
Revises: 0077_connector_proxy_calls
Create Date: 2026-04-26

Phase 3 of the OpenSail Automation Runtime rollout — App Composition.

The composition contract: a parent app calls into a child app ONLY via
``dispatch_app_action``, embeds child UI ONLY via signed view-embed tokens,
and queries child data ONLY via ``query_data_resource`` (which is itself a
``dispatch_app_action`` call). There is no path where the parent reaches
into the child's storage, K8s namespace, or process. This migration
materializes the two tables that back that contract.

1. ``app_instance_links`` — the install-time wiring. One row per
   ``(parent_install, child_install, alias)``; a parent app calls
   ``opensail.apps['<alias>'].actions.<name>`` and the runtime resolves the
   row, checks the action against ``granted_actions``, then dispatches.
   Granted scope arrays are positive lists drawn from
   ``manifest.dependencies[].needs`` — what the parent does NOT explicitly
   ask for, it does NOT get.
2. ``app_embeds`` — saved layout instances. When a user drags a CRM card
   into a dashboard slot, we persist a row here with the bound ``input``
   and ``layout_position``. The parent dashboard reads its rows at render
   time, mints a signed JWT per row via the embed-token signer, and
   renders an iframe per token.

Down revision is ``0077_connector_proxy_calls`` — that migration adds the
Connector Proxy primitives, this one layers App Composition on top.

Portable across Postgres (cloud) and SQLite (desktop sidecar) via
``postgresql.JSONB`` ↔ ``sa.JSON`` variant typing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0078_app_composition"
down_revision: str | Sequence[str] | None = "0077_connector_proxy_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_col() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON on SQLite — matches the chain convention."""
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # app_instance_links — parent install ⇒ child install wiring.
    # ------------------------------------------------------------------
    op.create_table(
        "app_instance_links",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "parent_install_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_install_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The parent's name for this child (e.g., "crm", "support"). Scoped
        # per parent install — uniqueness is enforced below.
        sa.Column("alias", sa.String(64), nullable=False),
        # Positive grants from manifest.dependencies[].needs. The runtime
        # rejects any cross-app call that targets a name not in these
        # lists with 403. Stored as JSON arrays of strings.
        sa.Column(
            "granted_actions",
            _json_col(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "granted_views",
            _json_col(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "granted_data_resources",
            _json_col(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Revocation is a soft-delete: ``UPDATE ... SET revoked_at=now()``.
        # The composition runtime treats a non-NULL revoked_at as a 404 on
        # alias resolution.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "parent_install_id", "alias", name="uq_app_instance_links_parent_alias"
        ),
    )
    op.create_index(
        "ix_ail_child_install_id",
        "app_instance_links",
        ["child_install_id"],
        unique=False,
    )
    op.create_index(
        "ix_ail_parent_install_id",
        "app_instance_links",
        ["parent_install_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # app_embeds — saved view-embed instances (e.g., dragged CRM card).
    # ------------------------------------------------------------------
    op.create_table(
        "app_embeds",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "parent_install_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_install_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("view_name", sa.String(128), nullable=False),
        # Bound input (e.g., {"account_id": "1234"}) — included verbatim in
        # the signed embed token at mint time.
        sa.Column(
            "input",
            _json_col(),
            nullable=False,
            server_default="{}",
        ),
        # Optional grid placement: { row, col, w, h }. NULL when the
        # embed is not part of a saved layout (e.g., a one-off render).
        sa.Column("layout_position", _json_col(), nullable=True),
        sa.Column(
            "created_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ae_parent_install_id",
        "app_embeds",
        ["parent_install_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ae_parent_install_id", table_name="app_embeds")
    op.drop_table("app_embeds")

    op.drop_index("ix_ail_parent_install_id", table_name="app_instance_links")
    op.drop_index("ix_ail_child_install_id", table_name="app_instance_links")
    op.drop_table("app_instance_links")
