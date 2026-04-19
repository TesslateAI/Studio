"""LiteLLM three-tier key ledger + usage_logs extension.

Revision ID: 0054_litellm_key_ledger
Revises: 0053_project_app_role
Create Date: 2026-04-14 00:01:00.000000

Context
-------
Tesslate Apps billing dispatcher needs per-session / per-invocation /
per-nested-call cost attribution, not just per-user. This migration lands:

1. `litellm_key_ledger` — one row per minted LiteLLM virtual key. Tracks tier
   (session/invocation/nested), parent linkage (for cascade-revoke), budget,
   spent, TTL, and state. See docs/proposed/plans/tesslate-apps.md §6 for
   the state machine.

2. `usage_logs` additions — session_id, installer_user_id, dimension,
   app_instance_id, litellm_key_id. Existing rows backfill to
   dimension='ai_compute' (safe default: today UsageLog only records AI spend).

Foreign keys to `app_instances` are intentionally omitted here — that table
lands in Wave 2. Columns are plain UUIDs now; a later migration adds the FK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0054_litellm_key_ledger"
down_revision: str | Sequence[str] | None = "0053_project_app_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- litellm_key_ledger ---------------------------------------------------
    op.create_table(
        "litellm_key_ledger",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("key_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "parent_key_id",
            sa.Text(),
            sa.ForeignKey(
                "litellm_key_ledger.key_id",
                ondelete="SET NULL",
                name="fk_litellm_key_ledger_parent",
            ),
            nullable=True,
        ),
        sa.Column(
            "tier",
            sa.String(16),
            nullable=False,
        ),  # session | invocation | nested
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "app_instance_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            nullable=True,
        ),
        sa.Column("budget_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column(
            "spent_usd",
            sa.Numeric(12, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("ttl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),  # pending | active | settling | settled | reaped | revoked | failed
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
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.create_index(
        "ix_litellm_key_ledger_parent_key_id",
        "litellm_key_ledger",
        ["parent_key_id"],
    )
    op.create_index(
        "ix_litellm_key_ledger_user_state",
        "litellm_key_ledger",
        ["user_id", "state"],
    )
    op.create_index(
        "ix_litellm_key_ledger_session_id",
        "litellm_key_ledger",
        ["session_id"],
    )
    op.create_index(
        "ix_litellm_key_ledger_app_instance_created",
        "litellm_key_ledger",
        ["app_instance_id", "created_at"],
    )
    # Reaper scan: only scan active rows with a TTL set.
    op.create_index(
        "ix_litellm_key_ledger_ttl_active",
        "litellm_key_ledger",
        ["ttl_at"],
        postgresql_where=sa.text("state = 'active'"),
    )

    # -- usage_logs extension -------------------------------------------------
    _is_sqlite = op.get_bind().dialect.name == "sqlite"
    _uuid_type = postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite")
    _installer_fk = [] if _is_sqlite else [sa.ForeignKey("users.id", ondelete="SET NULL")]
    op.add_column("usage_logs", sa.Column("session_id", _uuid_type, nullable=True))
    op.add_column(
        "usage_logs", sa.Column("installer_user_id", _uuid_type, *_installer_fk, nullable=True)
    )
    op.add_column(
        "usage_logs",
        sa.Column(
            "dimension",
            sa.String(24),
            nullable=False,
            server_default="ai_compute",
        ),
        # ai_compute | general_compute | storage | egress | mcp_tool_call | platform_fee
    )
    op.add_column("usage_logs", sa.Column("app_instance_id", _uuid_type, nullable=True))
    op.add_column("usage_logs", sa.Column("litellm_key_id", sa.Text(), nullable=True))

    op.create_index(
        "ix_usage_logs_app_instance_created",
        "usage_logs",
        ["app_instance_id", "created_at"],
    )
    op.create_index(
        "ix_usage_logs_installer_dimension_created",
        "usage_logs",
        ["installer_user_id", "dimension", "created_at"],
    )
    op.create_index("ix_usage_logs_session_id", "usage_logs", ["session_id"])
    op.create_index("ix_usage_logs_litellm_key_id", "usage_logs", ["litellm_key_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_logs_litellm_key_id", table_name="usage_logs")
    op.drop_index("ix_usage_logs_session_id", table_name="usage_logs")
    op.drop_index("ix_usage_logs_installer_dimension_created", table_name="usage_logs")
    op.drop_index("ix_usage_logs_app_instance_created", table_name="usage_logs")
    op.drop_column("usage_logs", "litellm_key_id")
    op.drop_column("usage_logs", "app_instance_id")
    op.drop_column("usage_logs", "dimension")
    op.drop_column("usage_logs", "installer_user_id")
    op.drop_column("usage_logs", "session_id")

    op.drop_index("ix_litellm_key_ledger_ttl_active", table_name="litellm_key_ledger")
    op.drop_index("ix_litellm_key_ledger_app_instance_created", table_name="litellm_key_ledger")
    op.drop_index("ix_litellm_key_ledger_session_id", table_name="litellm_key_ledger")
    op.drop_index("ix_litellm_key_ledger_user_state", table_name="litellm_key_ledger")
    op.drop_index("ix_litellm_key_ledger_parent_key_id", table_name="litellm_key_ledger")
    op.drop_table("litellm_key_ledger")
