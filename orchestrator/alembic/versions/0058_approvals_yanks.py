"""Tesslate Apps approvals, yanks, monitoring, adversarial, reputation.

Revision ID: 0058_approvals_yanks
Revises: 0057_app_bundles
Create Date: 2026-04-14 00:05:00.000000

Context
-------
Wave 2 continuation. Lands the approval pipeline, yank workflow with critical
two-admin rule, monitoring and adversarial suites, and creator reputation:

- app_submissions      : staged approval pipeline (stage0..3 -> approved|rejected).
- submission_checks    : per-stage check rows.
- yank_requests        : yank workflow with critical two-admin enforcement.
- yank_appeals         : 1:1 appeal on a yank_request.
- monitoring_runs      : canary / replay / drift observability.
- adversarial_suites   : named+versioned adversarial test suites (CAS-hashed).
- adversarial_runs     : per-version adversarial evaluations.
- creator_reputation   : per-user reputation score + counters.

See docs/proposed/plans/tesslate-apps.md §2.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0058_approvals_yanks"
down_revision: str | Sequence[str] | None = "0057_app_bundles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- app_submissions -----------------------------------------------------
    op.create_table(
        "app_submissions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_versions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "submitter_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "stage",
            sa.String(16),
            nullable=False,
            server_default="stage0",
        ),  # stage0 | stage1 | stage2 | stage3 | approved | rejected
        sa.Column(
            "stage_entered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sla_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewer_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decision",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),  # pending | approved | rejected | needs_changes
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_app_submissions_stage_sla",
        "app_submissions",
        ["stage", "sla_deadline_at"],
    )
    op.create_index(
        "ix_app_submissions_reviewer_user_id",
        "app_submissions",
        ["reviewer_user_id"],
    )

    # -- submission_checks ---------------------------------------------------
    op.create_table(
        "submission_checks",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "submission_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("check_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
        ),  # passed | failed | warning | errored
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_submission_checks_submission_created",
        "submission_checks",
        ["submission_id", "created_at"],
    )

    # -- yank_requests -------------------------------------------------------
    op.create_table(
        "yank_requests",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("severity", sa.String(16), nullable=False),  # low | medium | critical
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),  # pending | approved | rejected | appealed
        sa.Column(
            "primary_admin_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "secondary_admin_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT (severity = 'critical' AND status = 'approved'"
            " AND (primary_admin_id IS NULL OR secondary_admin_id IS NULL))",
            name="ck_yank_critical_two_admin",
        ),
    )
    op.create_index("ix_yank_requests_app_version_id", "yank_requests", ["app_version_id"])
    op.create_index(
        "ix_yank_requests_status_severity",
        "yank_requests",
        ["status", "severity"],
    )

    # -- yank_appeals --------------------------------------------------------
    op.create_table(
        "yank_appeals",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "yank_request_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("yank_requests.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "appellant_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),  # pending | upheld | overturned
        sa.Column(
            "reviewer_user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_yank_appeals_status", "yank_appeals", ["status"])

    # -- monitoring_runs -----------------------------------------------------
    op.create_table(
        "monitoring_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),  # canary | replay | drift
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
        ),  # pending | running | passed | failed | errored
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_monitoring_runs_version_kind_created",
        "monitoring_runs",
        ["app_version_id", "kind", "created_at"],
    )

    # -- adversarial_suites --------------------------------------------------
    op.create_table(
        "adversarial_suites",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("suite_yaml_cas_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", "version", name="uq_adversarial_suite_name_version"),
    )

    # -- adversarial_runs ----------------------------------------------------
    op.create_table(
        "adversarial_runs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"), primary_key=True
        ),
        sa.Column(
            "suite_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("adversarial_suites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "app_version_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("app_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(6, 3), nullable=True),
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_adversarial_runs_version_created",
        "adversarial_runs",
        ["app_version_id", "created_at"],
    )
    op.create_index("ix_adversarial_runs_suite_id", "adversarial_runs", ["suite_id"])

    # -- creator_reputation --------------------------------------------------
    op.create_table(
        "creator_reputation",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "score",
            sa.Numeric(6, 3),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "approvals_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "yanks_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "critical_yanks_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("creator_reputation")

    op.drop_index("ix_adversarial_runs_suite_id", table_name="adversarial_runs")
    op.drop_index("ix_adversarial_runs_version_created", table_name="adversarial_runs")
    op.drop_table("adversarial_runs")

    op.drop_table("adversarial_suites")

    op.drop_index("ix_monitoring_runs_version_kind_created", table_name="monitoring_runs")
    op.drop_table("monitoring_runs")

    op.drop_index("ix_yank_appeals_status", table_name="yank_appeals")
    op.drop_table("yank_appeals")

    op.drop_index("ix_yank_requests_status_severity", table_name="yank_requests")
    op.drop_index("ix_yank_requests_app_version_id", table_name="yank_requests")
    op.drop_table("yank_requests")

    op.drop_index("ix_submission_checks_submission_created", table_name="submission_checks")
    op.drop_table("submission_checks")

    op.drop_index("ix_app_submissions_reviewer_user_id", table_name="app_submissions")
    op.drop_index("ix_app_submissions_stage_sla", table_name="app_submissions")
    op.drop_table("app_submissions")
