"""CommunicationDestination — named gateway delivery targets.

Revision ID: 0079_comm_destinations
Revises: 0078_app_composition
Create Date: 2026-04-26

Phase 4 of the OpenSail Automation Runtime rollout — the
``CommunicationDestination`` primitive (see
``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
section "CommunicationDestination — gateway delivery target distinct
from ChannelConfig").

Today ``ChannelConfig`` is "one bot/app credential set" (one row per
Slack workspace / Telegram bot). What's missing is a stored, NAMED
destination *inside* that connection — so a user can configure once
"send standup digests to #standup, send incidents to Telegram chat
12345, daily summaries to my email" and reference these by ID from
many automations.

This migration adds:

1. ``communication_destinations`` — the new table. Each row points back
   to a ``ChannelConfig`` (the underlying credential set) and carries
   the kind / name / config blob / formatting policy.
2. ``automation_delivery_targets.destination_id`` becomes a real FK to
   ``communication_destinations.id`` (it shipped in 0074 as a plain
   GUID column reserved for this phase).

Down revision is ``0078_app_composition`` (Phase 3) — that migration
finished the App Composition primitives, this layers Phase 4 on top.

Portable across Postgres (cloud) and SQLite (desktop sidecar) via
``postgresql.JSONB`` ↔ ``sa.JSON`` variant typing and
``op.batch_alter_table`` for the FK alter SQLite cannot do in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0079_comm_destinations"
down_revision: str | Sequence[str] | None = "0078_app_composition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_col() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON on SQLite — matches the chain convention."""
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


# Allowed destination kinds. Kept as a CHECK rather than a Postgres ENUM
# so we can extend the set without an ENUM ALTER (which is non-trivial
# under SQLite parity).
_DESTINATION_KINDS = (
    "slack_channel",
    "slack_dm",
    "slack_thread",
    "telegram_chat",
    "telegram_topic",
    "discord_channel",
    "discord_dm",
    "email",
    "webhook",
    "web_inbox",
)

_FORMATTING_POLICIES = (
    "text",
    "blocks",
    "rich",
    "code_block",
    "inline_table",
    "jinja_template",
)


def _kind_check_clause() -> str:
    quoted = ", ".join(f"'{k}'" for k in _DESTINATION_KINDS)
    return f"kind IN ({quoted})"


def _formatting_check_clause() -> str:
    quoted = ", ".join(f"'{p}'" for p in _FORMATTING_POLICIES)
    return f"formatting_policy IN ({quoted})"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # communication_destinations — named gateway destination per
    # ChannelConfig.
    # ------------------------------------------------------------------
    op.create_table(
        "communication_destinations",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        # Either an owner user OR a team (or both — owner under a team).
        # Both are nullable so a row can be team-only (created by an
        # admin without pinning to a single user).
        sa.Column(
            "owner_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # The underlying connection (Slack workspace, Telegram bot, etc.).
        # CASCADE: removing the credential removes its named pointers.
        sa.Column(
            "channel_config_id",
            GUID(),
            sa.ForeignKey("channel_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        # {chat_id, thread_id?, email_address?, webhook_url?, signing_key?}
        sa.Column(
            "config",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "formatting_policy",
            sa.String(32),
            nullable=False,
            server_default="text",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            _kind_check_clause(),
            name="ck_communication_destinations_kind",
        ),
        sa.CheckConstraint(
            _formatting_check_clause(),
            name="ck_communication_destinations_formatting_policy",
        ),
    )
    op.create_index(
        "ix_cd_owner_user_id",
        "communication_destinations",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_cd_team_id",
        "communication_destinations",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "ix_cd_channel_config_id",
        "communication_destinations",
        ["channel_config_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # AutomationDeliveryTarget.destination_id — promote from plain GUID
    # column to a real FK now that the target table exists.
    #
    # CASCADE: when a destination is deleted, its fan-out edges go with
    # it. The automation definition itself stays — the user can re-wire
    # delivery to another destination.
    # ------------------------------------------------------------------
    with op.batch_alter_table("automation_delivery_targets") as batch_op:
        batch_op.create_foreign_key(
            "fk_adt_destination_id",
            "communication_destinations",
            ["destination_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("automation_delivery_targets") as batch_op:
        batch_op.drop_constraint("fk_adt_destination_id", type_="foreignkey")

    op.drop_index(
        "ix_cd_channel_config_id", table_name="communication_destinations"
    )
    op.drop_index("ix_cd_team_id", table_name="communication_destinations")
    op.drop_index("ix_cd_owner_user_id", table_name="communication_destinations")
    op.drop_table("communication_destinations")
