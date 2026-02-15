"""Initial schema - consolidated migration

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-18

This is a consolidated initial migration that creates all tables from scratch.
It replaces the previous fragmented migration chain and ensures fresh deployments
work reliably.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables."""

    # ==========================================================================
    # Users table (core authentication - fastapi-users compatible)
    # ==========================================================================
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("subscription_tier", sa.String(), nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("total_spend", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deployed_projects_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creator_stripe_account_id", sa.String(), nullable=True),
        sa.Column("litellm_api_key", sa.String(), nullable=True),
        sa.Column("litellm_user_id", sa.String(), nullable=True),
        sa.Column("diagram_model", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("twitter_handle", sa.String(100), nullable=True),
        sa.Column("github_username", sa.String(100), nullable=True),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("referral_code", sa.String(), nullable=True),
        sa.Column("referred_by", sa.String(), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_slug", "users", ["slug"], unique=True)
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"], unique=False)
    op.create_index("ix_users_litellm_api_key", "users", ["litellm_api_key"], unique=True)
    op.create_index("ix_users_litellm_user_id", "users", ["litellm_user_id"], unique=True)
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)

    # ==========================================================================
    # OAuth Accounts (fastapi-users)
    # ==========================================================================
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("oauth_name", sa.String(length=100), nullable=False),
        sa.Column("access_token", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column("refresh_token", sa.String(length=1024), nullable=True),
        sa.Column("account_id", sa.String(length=320), nullable=False),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="cascade"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_accounts_id", "oauth_accounts", ["id"], unique=False)
    op.create_index("ix_oauth_accounts_account_id", "oauth_accounts", ["account_id"], unique=False)
    op.create_index("ix_oauth_accounts_oauth_name", "oauth_accounts", ["oauth_name"], unique=False)

    # ==========================================================================
    # Access Tokens (fastapi-users)
    # ==========================================================================
    op.create_table(
        "access_tokens",
        sa.Column("token", sa.String(length=43), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="cascade"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index("ix_access_tokens_token", "access_tokens", ["token"], unique=False)
    op.create_index("ix_access_tokens_user_id", "access_tokens", ["user_id"], unique=False)

    # ==========================================================================
    # Marketplace Bases (needed before projects/containers)
    # ==========================================================================
    op.create_table(
        "marketplace_bases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("git_repo_url", sa.String(500), nullable=False),
        sa.Column("default_branch", sa.String(100), nullable=True, server_default="main"),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=True, server_default="📦"),
        sa.Column("preview_image", sa.String(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("pricing_type", sa.String(), nullable=False, server_default="free"),
        sa.Column("price", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("stripe_product_id", sa.String(), nullable=True),
        sa.Column("downloads", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("rating", sa.Float(), nullable=True, server_default="5.0"),
        sa.Column("reviews_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("tech_stack", sa.JSON(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_bases_id", "marketplace_bases", ["id"], unique=False)
    op.create_index("ix_marketplace_bases_slug", "marketplace_bases", ["slug"], unique=True)

    # ==========================================================================
    # Marketplace Agents
    # ==========================================================================
    op.create_table(
        "marketplace_agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=False, server_default="agent"),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=True),
        sa.Column("tools", sa.JSON(), nullable=True),
        sa.Column("tool_configs", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("is_forkable", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("parent_agent_id", sa.UUID(), nullable=True),
        sa.Column("forked_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("icon", sa.String(), nullable=True, server_default="🤖"),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("preview_image", sa.String(), nullable=True),
        sa.Column("pricing_type", sa.String(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("api_pricing_input", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("api_pricing_output", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("stripe_product_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True, server_default="closed"),
        sa.Column("requires_user_keys", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("downloads", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("rating", sa.Float(), nullable=True, server_default="5.0"),
        sa.Column("reviews_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("usage_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("required_models", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("is_published", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["forked_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_agent_id"], ["marketplace_agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketplace_agents_id", "marketplace_agents", ["id"], unique=False)
    op.create_index("ix_marketplace_agents_slug", "marketplace_agents", ["slug"], unique=True)

    # ==========================================================================
    # Projects
    # ==========================================================================
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("has_git_repo", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("git_remote_url", sa.String(500), nullable=True),
        sa.Column("architecture_diagram", sa.Text(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("network_name", sa.String(), nullable=True),
        sa.Column("volume_name", sa.String(), nullable=True),
        sa.Column("deploy_type", sa.String(), nullable=True, server_default="development"),
        sa.Column("is_deployed", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_payment_intent", sa.String(), nullable=True),
        sa.Column("environment_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hibernated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_snapshot_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_id", "projects", ["id"], unique=False)
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)

    # ==========================================================================
    # Project Snapshots (EBS VolumeSnapshots for hibernation)
    # ==========================================================================
    op.create_table(
        "project_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_name", sa.String(255), nullable=False),
        sa.Column("snapshot_namespace", sa.String(255), nullable=False),
        sa.Column("pvc_name", sa.String(255), nullable=True),
        sa.Column("volume_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("snapshot_type", sa.String(50), nullable=False, server_default="hibernation"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_soft_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("soft_delete_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_snapshots_id", "project_snapshots", ["id"], unique=False)
    op.create_index(
        "ix_project_snapshots_snapshot_name", "project_snapshots", ["snapshot_name"], unique=False
    )
    op.create_index(
        "ix_project_snapshots_project_id", "project_snapshots", ["project_id"], unique=False
    )
    op.create_index(
        "ix_project_snapshots_project_created", "project_snapshots", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_project_snapshots_soft_delete",
        "project_snapshots",
        ["is_soft_deleted", "soft_delete_expires_at"],
    )

    # ==========================================================================
    # Deployment Credentials (needed before containers for credentials_id FK)
    # ==========================================================================
    op.create_table(
        "deployment_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deployment_credentials_id", "deployment_credentials", ["id"], unique=False)
    op.create_index(
        "ix_deployment_credentials_user_id", "deployment_credentials", ["user_id"], unique=False
    )
    op.create_index(
        "ix_deployment_credentials_project_id",
        "deployment_credentials",
        ["project_id"],
        unique=False,
    )

    # ==========================================================================
    # Containers
    # ==========================================================================
    op.create_table(
        "containers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("base_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("directory", sa.String(), nullable=False),
        sa.Column("container_name", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("internal_port", sa.Integer(), nullable=True),
        sa.Column("environment_vars", sa.JSON(), nullable=True),
        sa.Column("dockerfile_path", sa.String(), nullable=True),
        sa.Column("volume_name", sa.String(), nullable=True),
        sa.Column("container_type", sa.String(), nullable=False, server_default="base"),
        sa.Column("service_slug", sa.String(), nullable=True),
        sa.Column("deployment_mode", sa.String(), nullable=True, server_default="container"),
        sa.Column("external_endpoint", sa.String(), nullable=True),
        sa.Column("credentials_id", sa.UUID(), nullable=True),
        sa.Column("position_x", sa.Float(), nullable=True, server_default="0"),
        sa.Column("position_y", sa.Float(), nullable=True, server_default="0"),
        sa.Column("status", sa.String(), nullable=True, server_default="stopped"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["base_id"], ["marketplace_bases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["credentials_id"], ["deployment_credentials.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_containers_id", "containers", ["id"], unique=False)

    # ==========================================================================
    # Container Connections
    # ==========================================================================
    op.create_table(
        "container_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source_container_id", sa.UUID(), nullable=False),
        sa.Column("target_container_id", sa.UUID(), nullable=False),
        sa.Column("connection_type", sa.String(), nullable=True, server_default="depends_on"),
        sa.Column("connector_type", sa.String(), nullable=True, server_default="env_injection"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_container_id"], ["containers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_container_id"], ["containers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_container_connections_id", "container_connections", ["id"], unique=False)

    # ==========================================================================
    # Browser Previews
    # ==========================================================================
    op.create_table(
        "browser_previews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("connected_container_id", sa.UUID(), nullable=True),
        sa.Column("position_x", sa.Float(), nullable=True, server_default="0"),
        sa.Column("position_y", sa.Float(), nullable=True, server_default="0"),
        sa.Column("current_path", sa.String(), nullable=True, server_default="/"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["connected_container_id"], ["containers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_previews_id", "browser_previews", ["id"], unique=False)

    # ==========================================================================
    # Project Files
    # ==========================================================================
    op.create_table(
        "project_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_files_id", "project_files", ["id"], unique=False)

    # ==========================================================================
    # Project Assets
    # ==========================================================================
    op.create_table(
        "project_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("directory", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_assets_id", "project_assets", ["id"], unique=False)

    # ==========================================================================
    # Chats
    # ==========================================================================
    op.create_table(
        "chats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_id", "chats", ["id"], unique=False)

    # ==========================================================================
    # Messages
    # ==========================================================================
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("message_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)

    # ==========================================================================
    # Agent Command Logs
    # ==========================================================================
    op.create_table(
        "agent_command_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("working_dir", sa.String(), nullable=True, server_default="."),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_command_logs_id", "agent_command_logs", ["id"], unique=False)

    # ==========================================================================
    # Pod Access Logs
    # ==========================================================================
    op.create_table(
        "pod_access_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expected_user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("request_uri", sa.String(), nullable=True),
        sa.Column("request_host", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pod_access_logs_id", "pod_access_logs", ["id"], unique=False)

    # ==========================================================================
    # Shell Sessions
    # ==========================================================================
    op.create_table(
        "shell_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("container_name", sa.String(), nullable=False),
        sa.Column("command", sa.String(), nullable=True, server_default="/bin/bash"),
        sa.Column("working_dir", sa.String(), nullable=True, server_default="/app"),
        sa.Column("terminal_rows", sa.Integer(), nullable=True, server_default="24"),
        sa.Column("terminal_cols", sa.Integer(), nullable=True, server_default="80"),
        sa.Column("status", sa.String(), nullable=True, server_default="initializing"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bytes_read", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("bytes_written", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("total_reads", sa.Integer(), nullable=True, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shell_sessions_id", "shell_sessions", ["id"], unique=False)
    op.create_index("ix_shell_sessions_session_id", "shell_sessions", ["session_id"], unique=True)

    # ==========================================================================
    # GitHub Credentials
    # ==========================================================================
    op.create_table(
        "github_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(500), nullable=True),
        sa.Column("state", sa.String(255), nullable=True),
        sa.Column("github_username", sa.String(255), nullable=False),
        sa.Column("github_email", sa.String(255), nullable=True),
        sa.Column("github_user_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_github_credentials_id", "github_credentials", ["id"], unique=False)

    # ==========================================================================
    # Git Provider Credentials
    # ==========================================================================
    op.create_table(
        "git_provider_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(500), nullable=True),
        sa.Column("provider_username", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255), nullable=True),
        sa.Column("provider_user_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_git_provider_credentials_id", "git_provider_credentials", ["id"], unique=False
    )
    op.create_index(
        "ix_git_provider_credentials_user_provider",
        "git_provider_credentials",
        ["user_id", "provider"],
        unique=True,
    )

    # ==========================================================================
    # Git Repositories
    # ==========================================================================
    op.create_table(
        "git_repositories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("repo_url", sa.String(500), nullable=False),
        sa.Column("repo_name", sa.String(255), nullable=True),
        sa.Column("repo_owner", sa.String(255), nullable=True),
        sa.Column("default_branch", sa.String(100), nullable=True, server_default="main"),
        sa.Column("auth_method", sa.String(20), nullable=True, server_default="oauth"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=True),
        sa.Column("last_commit_sha", sa.String(40), nullable=True),
        sa.Column("auto_push", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("auto_pull", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_git_repositories_id", "git_repositories", ["id"], unique=False)

    # ==========================================================================
    # Deployments
    # ==========================================================================
    op.create_table(
        "deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("deployment_id", sa.String(255), nullable=True),
        sa.Column("deployment_url", sa.String(500), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("logs", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deployments_id", "deployments", ["id"], unique=False)
    op.create_index("ix_deployments_project_id", "deployments", ["project_id"], unique=False)
    op.create_index("ix_deployments_user_id", "deployments", ["user_id"], unique=False)
    op.create_index("ix_deployments_provider", "deployments", ["provider"], unique=False)
    op.create_index("ix_deployments_status", "deployments", ["status"], unique=False)
    op.create_index("ix_deployments_created_at", "deployments", ["created_at"], unique=False)

    # ==========================================================================
    # User Purchased Agents
    # ==========================================================================
    op.create_table(
        "user_purchased_agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column(
            "purchase_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("purchase_type", sa.String(), nullable=False),
        sa.Column("stripe_payment_intent", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("selected_model", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["marketplace_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_purchased_agents_id", "user_purchased_agents", ["id"], unique=False)

    # ==========================================================================
    # User Purchased Bases
    # ==========================================================================
    op.create_table(
        "user_purchased_bases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("base_id", sa.UUID(), nullable=False),
        sa.Column(
            "purchase_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("purchase_type", sa.String(), nullable=False),
        sa.Column("stripe_payment_intent", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.ForeignKeyConstraint(["base_id"], ["marketplace_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_purchased_bases_id", "user_purchased_bases", ["id"], unique=False)

    # ==========================================================================
    # Project Agents
    # ==========================================================================
    op.create_table(
        "project_agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["marketplace_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_agents_id", "project_agents", ["id"], unique=False)

    # ==========================================================================
    # Agent Reviews
    # ==========================================================================
    op.create_table(
        "agent_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["marketplace_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_reviews_id", "agent_reviews", ["id"], unique=False)

    # ==========================================================================
    # Base Reviews
    # ==========================================================================
    op.create_table(
        "base_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("base_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["base_id"], ["marketplace_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_base_reviews_id", "base_reviews", ["id"], unique=False)

    # ==========================================================================
    # Workflow Templates
    # ==========================================================================
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(), nullable=True, server_default="🔗"),
        sa.Column("preview_image", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("template_definition", sa.JSON(), nullable=False),
        sa.Column("required_credentials", sa.JSON(), nullable=True),
        sa.Column("pricing_type", sa.String(), nullable=True, server_default="free"),
        sa.Column("price", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("stripe_product_id", sa.String(), nullable=True),
        sa.Column("downloads", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("rating", sa.Float(), nullable=True, server_default="5.0"),
        sa.Column("reviews_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("is_featured", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_templates_id", "workflow_templates", ["id"], unique=False)
    op.create_index("ix_workflow_templates_slug", "workflow_templates", ["slug"], unique=True)

    # ==========================================================================
    # User API Keys
    # ==========================================================================
    op.create_table(
        "user_api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("auth_type", sa.String(), nullable=False, server_default="api_key"),
        sa.Column("key_name", sa.String(), nullable=True),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("provider_metadata", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_api_keys_id", "user_api_keys", ["id"], unique=False)

    # ==========================================================================
    # User Custom Models
    # ==========================================================================
    op.create_table(
        "user_custom_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="openrouter"),
        sa.Column("pricing_input", sa.Float(), nullable=True),
        sa.Column("pricing_output", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_custom_models_id", "user_custom_models", ["id"], unique=False)

    # ==========================================================================
    # Agent Co-Installs
    # ==========================================================================
    op.create_table(
        "agent_co_installs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("related_agent_id", sa.UUID(), nullable=False),
        sa.Column("co_install_count", sa.Integer(), nullable=True, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["marketplace_agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["related_agent_id"], ["marketplace_agents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "related_agent_id", name="uq_agent_co_install_pair"),
    )
    op.create_index("ix_agent_co_installs_id", "agent_co_installs", ["id"], unique=False)
    op.create_index(
        "ix_agent_co_installs_agent_id", "agent_co_installs", ["agent_id"], unique=False
    )
    op.create_index(
        "ix_agent_co_installs_related_agent_id",
        "agent_co_installs",
        ["related_agent_id"],
        unique=False,
    )

    # ==========================================================================
    # Marketplace Transactions
    # ==========================================================================
    op.create_table(
        "marketplace_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("creator_id", sa.UUID(), nullable=True),
        sa.Column("transaction_type", sa.String(), nullable=False),
        sa.Column("amount_total", sa.Integer(), nullable=False),
        sa.Column("amount_creator", sa.Integer(), nullable=False),
        sa.Column("amount_platform", sa.Integer(), nullable=False),
        sa.Column("stripe_payment_intent", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(), nullable=True),
        sa.Column("payout_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("payout_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_payout_id", sa.String(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["marketplace_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_marketplace_transactions_id", "marketplace_transactions", ["id"], unique=False
    )

    # ==========================================================================
    # Credit Purchases
    # ==========================================================================
    op.create_table(
        "credit_purchases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("credits_amount", sa.Integer(), nullable=False),
        sa.Column("stripe_payment_intent", sa.String(), nullable=False),
        sa.Column("stripe_checkout_session", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_purchases_id", "credit_purchases", ["id"], unique=False)
    op.create_index(
        "ix_credit_purchases_stripe_payment_intent",
        "credit_purchases",
        ["stripe_payment_intent"],
        unique=True,
    )

    # ==========================================================================
    # Usage Logs
    # ==========================================================================
    op.create_table(
        "usage_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("tokens_input", sa.Integer(), nullable=False),
        sa.Column("tokens_output", sa.Integer(), nullable=False),
        sa.Column("cost_input", sa.Integer(), nullable=False),
        sa.Column("cost_output", sa.Integer(), nullable=False),
        sa.Column("cost_total", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.UUID(), nullable=True),
        sa.Column("creator_revenue", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("platform_revenue", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("billed_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("invoice_id", sa.String(), nullable=True),
        sa.Column("billed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["marketplace_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_logs_id", "usage_logs", ["id"], unique=False)
    op.create_index("ix_usage_logs_created_at", "usage_logs", ["created_at"], unique=False)

    # ==========================================================================
    # Feedback Posts
    # ==========================================================================
    op.create_table(
        "feedback_posts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("upvote_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_posts_id", "feedback_posts", ["id"], unique=False)
    op.create_index(
        "ix_feedback_posts_upvote_count", "feedback_posts", ["upvote_count"], unique=False
    )
    op.create_index("ix_feedback_posts_created_at", "feedback_posts", ["created_at"], unique=False)

    # ==========================================================================
    # Feedback Upvotes
    # ==========================================================================
    op.create_table(
        "feedback_upvotes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "feedback_id", name="uq_feedback_upvote_user_post"),
    )
    op.create_index("ix_feedback_upvotes_id", "feedback_upvotes", ["id"], unique=False)
    op.create_index("ix_feedback_upvotes_user_id", "feedback_upvotes", ["user_id"], unique=False)
    op.create_index(
        "ix_feedback_upvotes_feedback_id", "feedback_upvotes", ["feedback_id"], unique=False
    )

    # ==========================================================================
    # Feedback Comments
    # ==========================================================================
    op.create_table(
        "feedback_comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_comments_id", "feedback_comments", ["id"], unique=False)
    op.create_index(
        "ix_feedback_comments_feedback_id", "feedback_comments", ["feedback_id"], unique=False
    )
    op.create_index(
        "ix_feedback_comments_created_at", "feedback_comments", ["created_at"], unique=False
    )

    # ==========================================================================
    # Kanban Boards
    # ==========================================================================
    op.create_table(
        "kanban_boards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default="Project Board"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_kanban_boards_id", "kanban_boards", ["id"], unique=False)

    # ==========================================================================
    # Kanban Columns
    # ==========================================================================
    op.create_table(
        "kanban_columns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("is_backlog", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("is_completed", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("task_limit", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["board_id"], ["kanban_boards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kanban_columns_id", "kanban_columns", ["id"], unique=False)

    # ==========================================================================
    # Kanban Tasks
    # ==========================================================================
    op.create_table(
        "kanban_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("board_id", sa.UUID(), nullable=False),
        sa.Column("column_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("task_type", sa.String(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("reporter_id", sa.UUID(), nullable=True),
        sa.Column("estimate_hours", sa.Integer(), nullable=True),
        sa.Column("spent_hours", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["board_id"], ["kanban_boards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["column_id"], ["kanban_columns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kanban_tasks_id", "kanban_tasks", ["id"], unique=False)

    # ==========================================================================
    # Kanban Task Comments
    # ==========================================================================
    op.create_table(
        "kanban_task_comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["task_id"], ["kanban_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kanban_task_comments_id", "kanban_task_comments", ["id"], unique=False)

    # ==========================================================================
    # Project Notes
    # ==========================================================================
    op.create_table(
        "project_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_format", sa.String(), nullable=True, server_default="html"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_project_notes_id", "project_notes", ["id"], unique=False)


def downgrade() -> None:
    """Drop all tables in reverse order."""
    op.drop_table("project_notes")
    op.drop_table("kanban_task_comments")
    op.drop_table("kanban_tasks")
    op.drop_table("kanban_columns")
    op.drop_table("kanban_boards")
    op.drop_table("feedback_comments")
    op.drop_table("feedback_upvotes")
    op.drop_table("feedback_posts")
    op.drop_table("usage_logs")
    op.drop_table("credit_purchases")
    op.drop_table("marketplace_transactions")
    op.drop_table("agent_co_installs")
    op.drop_table("user_custom_models")
    op.drop_table("user_api_keys")
    op.drop_table("workflow_templates")
    op.drop_table("base_reviews")
    op.drop_table("agent_reviews")
    op.drop_table("project_agents")
    op.drop_table("user_purchased_bases")
    op.drop_table("user_purchased_agents")
    op.drop_table("deployments")
    op.drop_table("git_repositories")
    op.drop_table("git_provider_credentials")
    op.drop_table("github_credentials")
    op.drop_table("shell_sessions")
    op.drop_table("pod_access_logs")
    op.drop_table("agent_command_logs")
    op.drop_table("messages")
    op.drop_table("chats")
    op.drop_table("project_assets")
    op.drop_table("project_files")
    op.drop_table("browser_previews")
    op.drop_table("container_connections")
    op.drop_table("containers")
    op.drop_table("deployment_credentials")
    op.drop_table("project_snapshots")
    op.drop_table("projects")
    op.drop_table("marketplace_agents")
    op.drop_table("marketplace_bases")
    op.drop_table("access_tokens")
    op.drop_table("oauth_accounts")
    op.drop_table("users")
