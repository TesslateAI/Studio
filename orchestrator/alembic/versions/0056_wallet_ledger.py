"""Tesslate Apps wallet + spend records.

Revision ID: 0056_wallet_ledger
Revises: 0055_apps_core
Create Date: 2026-04-14 00:03:00.000000

Context
-------
Wave 1 continuation. Lands the wallet/ledger system for per-payer attribution
under the Apps billing dispatcher:

- wallets              : per-owner USD balance (creator | platform | installer).
- wallet_ledger_entries: append-only ledger of credits/debits/settlements.
- spend_records        : per-event spend attribution (dimension, payer) with
                         optional link to usage_logs (AI compute) or raw events.

See docs/proposed/plans/tesslate-apps.md §6.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0056_wallet_ledger"
down_revision: str | Sequence[str] | None = "0055_apps_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- wallets -------------------------------------------------------------
    op.create_table(
        "wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_type",
            sa.String(16),
            nullable=False,
        ),  # creator | platform | installer
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "balance_usd",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),  # active | frozen
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
    # Partial UNIQUE: one active wallet per (owner_type, owner_user_id).
    # NOTE: Postgres treats NULLs as distinct, so platform wallets (NULL owner)
    # are not uniquely constrained here — singleton platform wallet is
    # enforced at the service layer.
    op.create_index(
        "uq_wallet_owner_active",
        "wallets",
        ["owner_type", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    # -- wallet_ledger_entries ----------------------------------------------
    op.create_table(
        "wallet_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "wallet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wallets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("delta_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column(
            "kind",
            sa.String(24),
            nullable=False,
        ),  # credit | debit | transfer | settlement | adjustment
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "meta",
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
    )
    op.create_index(
        "ix_wallet_ledger_entries_wallet_created",
        "wallet_ledger_entries",
        ["wallet_id", "created_at"],
    )
    op.create_index(
        "ix_wallet_ledger_entries_reference",
        "wallet_ledger_entries",
        ["reference_type", "reference_id"],
    )

    # -- spend_records -------------------------------------------------------
    op.create_table(
        "spend_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # No FK to app_instances this wave — avoid circular / ordering concern.
        sa.Column("app_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "installer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dimension",
            sa.String(24),
            nullable=False,
        ),  # ai_compute | general_compute | storage | egress | mcp_tool_call | platform_fee
        sa.Column(
            "payer",
            sa.String(16),
            nullable=False,
        ),  # creator | platform | installer | byok
        sa.Column(
            "payer_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("litellm_key_id", sa.Text(), nullable=True),
        sa.Column(
            "usage_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usage_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "settled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta",
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
    )
    op.create_index(
        "ix_spend_records_app_instance_created",
        "spend_records",
        ["app_instance_id", "created_at"],
    )
    op.create_index(
        "ix_spend_records_payer_dimension",
        "spend_records",
        ["payer_user_id", "dimension"],
    )
    op.create_index("ix_spend_records_session_id", "spend_records", ["session_id"])
    # Partial index for the settlement reaper: only scan unsettled rows.
    op.create_index(
        "ix_spend_records_unsettled",
        "spend_records",
        ["created_at"],
        postgresql_where=sa.text("settled = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_spend_records_unsettled", table_name="spend_records")
    op.drop_index("ix_spend_records_session_id", table_name="spend_records")
    op.drop_index("ix_spend_records_payer_dimension", table_name="spend_records")
    op.drop_index("ix_spend_records_app_instance_created", table_name="spend_records")
    op.drop_table("spend_records")

    op.drop_index("ix_wallet_ledger_entries_reference", table_name="wallet_ledger_entries")
    op.drop_index("ix_wallet_ledger_entries_wallet_created", table_name="wallet_ledger_entries")
    op.drop_table("wallet_ledger_entries")

    op.drop_index("uq_wallet_owner_active", table_name="wallets")
    op.drop_table("wallets")
