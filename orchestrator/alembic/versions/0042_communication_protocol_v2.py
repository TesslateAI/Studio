"""Communication Protocol v2 — gateway, sessions, identity, schedules

Revision ID: 0042_comm_proto_v2
Revises: 0041_add_team_theme_preset
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0042_comm_proto_v2"
down_revision = "0041_team_theme_preset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Chat: gateway session fields ---
    op.add_column("chats", sa.Column("session_key", sa.String(255), nullable=True))
    op.add_column("chats", sa.Column("platform", sa.String(20), nullable=True))
    op.add_column("chats", sa.Column("platform_chat_id", sa.String(255), nullable=True))
    op.add_column("chats", sa.Column("platform_thread_id", sa.String(255), nullable=True))
    op.add_column(
        "chats",
        sa.Column(
            "channel_config_id",
            UUID(as_uuid=True),
            sa.ForeignKey("channel_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "chats",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("chats", sa.Column("idle_timeout_minutes", sa.Integer(), nullable=True))

    op.create_index("ix_chats_session_key", "chats", ["session_key"], unique=True)

    # --- ChannelConfig: gateway shard ---
    op.add_column(
        "channel_configs",
        sa.Column("gateway_shard", sa.Integer(), server_default="0", nullable=False),
    )

    # --- PlatformIdentity ---
    op.create_table(
        "platform_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("platform_user_id", sa.String(255), nullable=False),
        sa.Column("platform_username", sa.String(255), nullable=True),
        sa.Column("is_verified", sa.Boolean(), default=False),
        sa.Column("pairing_code", sa.String(8), nullable=True),
        sa.Column("pairing_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("platform", "platform_user_id", name="uq_platform_identity"),
    )
    op.create_index("ix_platform_identities_user_id", "platform_identities", ["user_id"])

    # --- AgentSchedule ---
    op.create_table(
        "agent_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("normalized_cron", sa.String(100), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(50), server_default="UTC"),
        sa.Column("deliver", sa.String(100), server_default="origin"),
        sa.Column("origin_platform", sa.String(20), nullable=True),
        sa.Column("origin_chat_id", sa.String(255), nullable=True),
        sa.Column("origin_config_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("repeat", sa.Integer(), nullable=True),
        sa.Column("runs_completed", sa.Integer(), server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_task_id", sa.String(), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_schedules_user_id", "agent_schedules", ["user_id"])
    op.create_index("ix_agent_schedules_next_run", "agent_schedules", ["next_run_at"])


def downgrade() -> None:
    op.drop_table("agent_schedules")
    op.drop_table("platform_identities")
    op.drop_column("channel_configs", "gateway_shard")
    op.drop_index("ix_chats_session_key", table_name="chats")
    op.drop_column("chats", "idle_timeout_minutes")
    op.drop_column("chats", "last_active_at")
    op.drop_column("chats", "channel_config_id")
    op.drop_column("chats", "platform_thread_id")
    op.drop_column("chats", "platform_chat_id")
    op.drop_column("chats", "platform")
    op.drop_column("chats", "session_key")
