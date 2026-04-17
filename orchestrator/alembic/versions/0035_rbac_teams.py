"""RBAC: teams, memberships, invitations, audit logs

Creates 5 new tables (teams, team_memberships, project_memberships,
team_invitations, audit_logs), adds team_id + visibility to projects,
default_team_id to users, team_id to usage_logs + credit_purchases.

Data migration: creates a personal team for every existing user, copies
billing fields, creates admin membership, links all projects.

Revision ID: 0035_rbac_teams
Revises: 0034_refresh_tokens
"""

revision = "0035_rbac_teams"
down_revision = "0034_refresh_tokens"
branch_labels = None
depends_on = None

import sqlalchemy as sa  # noqa: E402
from alembic import op  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.types.guid import GUID  # noqa: E402


def upgrade() -> None:
    # ── 1. Create teams table ───────────────────────────────────────────
    op.create_table(
        "teams",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("is_personal", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Billing (copied from users during data migration)
        sa.Column("subscription_tier", sa.String, nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String, nullable=True, unique=True),
        sa.Column("stripe_subscription_id", sa.String, nullable=True),
        sa.Column("total_spend", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bundled_credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("purchased_credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("daily_credits", sa.Integer, nullable=False, server_default="5"),
        sa.Column("signup_bonus_credits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("signup_bonus_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credits_reset_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_credits_reset_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("support_tier", sa.String(20), nullable=False, server_default="community"),
        sa.Column("deployed_projects_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_teams_stripe_customer_id", "teams", ["stripe_customer_id"])

    # ── 2. Create team_memberships table ────────────────────────────────
    op.create_table(
        "team_memberships",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "invited_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_memberships_team_user"),
    )
    op.create_index("ix_team_memberships_user_id", "team_memberships", ["user_id"])

    # ── 3. Create project_memberships table ─────────────────────────────
    op.create_table(
        "project_memberships",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "granted_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
    )
    op.create_index("ix_project_memberships_user_id", "project_memberships", ["user_id"])

    # ── 4. Create team_invitations table ────────────────────────────────
    op.create_table(
        "team_invitations",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token", sa.String(64), unique=True, nullable=False),
        sa.Column("invite_type", sa.String(20), nullable=False, server_default="email"),
        sa.Column(
            "invited_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses", sa.Integer, nullable=True),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_team_invitations_token", "team_invitations", ["token"])
    op.create_index("ix_team_invitations_team_email", "team_invitations", ["team_id", "email"])

    # ── 5. Create audit_logs table ──────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", GUID(), nullable=True),
        sa.Column("details", postgresql.JSON, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_logs_team_created", "audit_logs", ["team_id", "created_at"])
    op.create_index("ix_audit_logs_project_created", "audit_logs", ["project_id", "created_at"])
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # ── 6. Add columns to existing tables ───────────────────────────────

    # projects: team_id (nullable initially) + visibility
    op.add_column("projects", sa.Column("team_id", GUID(), nullable=True))
    op.add_column(
        "projects", sa.Column("visibility", sa.String(20), nullable=False, server_default="team")
    )
    with op.batch_alter_table("projects") as batch_op:
        batch_op.create_foreign_key(
            "fk_projects_team_id", "teams", ["team_id"], ["id"], ondelete="CASCADE"
        )

    # users: default_team_id
    op.add_column("users", sa.Column("default_team_id", GUID(), nullable=True))
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_foreign_key(
            "fk_users_default_team", "teams", ["default_team_id"], ["id"], ondelete="SET NULL"
        )

    # usage_logs: team_id
    op.add_column("usage_logs", sa.Column("team_id", GUID(), nullable=True))
    with op.batch_alter_table("usage_logs") as batch_op:
        batch_op.create_foreign_key(
            "fk_usage_logs_team_id", "teams", ["team_id"], ["id"], ondelete="SET NULL"
        )

    # credit_purchases: team_id
    op.add_column("credit_purchases", sa.Column("team_id", GUID(), nullable=True))
    with op.batch_alter_table("credit_purchases") as batch_op:
        batch_op.create_foreign_key(
            "fk_credit_purchases_team_id",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # ── 7. Data migration: create personal teams for existing users ─────
    # Using raw SQL for bulk efficiency in migration context.
    if op.get_bind().dialect.name != "postgresql":
        op.create_index("ix_projects_team_id", "projects", ["team_id"])
        return
    op.execute("""
        -- For each existing user, create a personal team with their billing data
        INSERT INTO teams (
            id, name, slug, is_personal, created_by_id,
            subscription_tier, stripe_customer_id, stripe_subscription_id,
            total_spend, bundled_credits, purchased_credits, daily_credits,
            signup_bonus_credits, signup_bonus_expires_at,
            credits_reset_date, daily_credits_reset_date,
            support_tier, deployed_projects_count,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            u.name || '''s Team',
            u.slug || '-team',
            true,
            u.id,
            COALESCE(u.subscription_tier, 'free'),
            u.stripe_customer_id,
            u.stripe_subscription_id,
            COALESCE(u.total_spend, 0),
            COALESCE(u.bundled_credits, 0),
            COALESCE(u.purchased_credits, 0),
            COALESCE(u.daily_credits, 0),
            COALESCE(u.signup_bonus_credits, 0),
            u.signup_bonus_expires_at,
            u.credits_reset_date,
            u.daily_credits_reset_date,
            COALESCE(u.support_tier, 'community'),
            COALESCE(u.deployed_projects_count, 0),
            COALESCE(u.created_at, now()),
            now()
        FROM users u;
    """)

    # Create admin membership for each user in their personal team
    op.execute("""
        INSERT INTO team_memberships (id, team_id, user_id, role, is_active, joined_at, created_at)
        SELECT
            gen_random_uuid(),
            t.id,
            t.created_by_id,
            'admin',
            true,
            now(),
            now()
        FROM teams t
        WHERE t.is_personal = true;
    """)

    # Set user.default_team_id to their personal team
    op.execute("""
        UPDATE users u
        SET default_team_id = t.id
        FROM teams t
        WHERE t.created_by_id = u.id AND t.is_personal = true;
    """)

    # Set project.team_id to the owner's personal team
    op.execute("""
        UPDATE projects p
        SET team_id = t.id
        FROM teams t
        WHERE t.created_by_id = p.owner_id AND t.is_personal = true;
    """)

    # Set all project visibility to 'team'
    op.execute("""
        UPDATE projects SET visibility = 'team' WHERE visibility IS NULL;
    """)

    # ── 8. Make team_id NOT NULL on projects ────────────────────────────
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column("team_id", nullable=False)

    # ── 9. Add index on projects.team_id ────────────────────────────────
    op.create_index("ix_projects_team_id", "projects", ["team_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_projects_team_id", table_name="projects")

    # Drop foreign keys
    with op.batch_alter_table("credit_purchases") as batch_op:
        batch_op.drop_constraint("fk_credit_purchases_team_id", type_="foreignkey")
    with op.batch_alter_table("usage_logs") as batch_op:
        batch_op.drop_constraint("fk_usage_logs_team_id", type_="foreignkey")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_default_team", type_="foreignkey")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("fk_projects_team_id", type_="foreignkey")

    # Drop added columns
    op.drop_column("credit_purchases", "team_id")
    op.drop_column("usage_logs", "team_id")
    op.drop_column("users", "default_team_id")
    op.drop_column("projects", "visibility")
    op.drop_column("projects", "team_id")

    # Drop new tables (reverse order of creation)
    op.drop_table("audit_logs")
    op.drop_table("team_invitations")
    op.drop_table("project_memberships")
    op.drop_table("team_memberships")
    op.drop_table("teams")
