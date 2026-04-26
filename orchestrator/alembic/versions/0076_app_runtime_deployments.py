"""AppRuntimeDeployment — runtime identity separate from logical install (Phase 3).

Revision ID: 0076_app_runtime_deployments
Revises: 0075_invocation_subjects
Create Date: 2026-04-26

Phase 3 of the OpenSail Automation Runtime rollout.

Creates the ``app_runtime_deployments`` table — the primitive that
separates "where does this actually run, with what replica policy, on
whose tenancy?" from ``AppInstance`` ("which user owns this install?").
One install != one runtime in shared-singleton mode: many ``AppInstance``
rows point at one ``AppRuntimeDeployment`` row.

What this migration does:

1. Creates ``app_runtime_deployments`` with the constraint matrix from
   the plan (``per_install_volume`` ⟹ ``max_replicas=1``; same for
   ``service_pvc``; ``max_replicas >= min_replicas``;
   ``desired_replicas BETWEEN min_replicas AND max_replicas``; CHECKs on
   the ``tenancy_model`` and ``state_model`` enums).
2. Creates two indexes on ``app_id`` and ``runtime_project_id`` so the
   installer's "find a shared-singleton row for this app/version" lookup
   and per-project teardown queries stay constant-time.
3. Attaches the deferred FK from ``app_instances.runtime_deployment_id``
   (column added in 0074, kept nullable for backward compat) to
   ``app_runtime_deployments.id``. ``ON DELETE SET NULL`` so destroying a
   deployment row never destroys the install rows that reference it —
   uninstall is the path for removing instances.

Backward compat: existing ``app_instances`` rows have
``runtime_deployment_id=NULL`` and stay that way. The next install/upgrade
under the new manifest schema mints the runtime row.

Portable across Postgres (cloud) and SQLite (desktop sidecar) via
``op.batch_alter_table`` for the FK alter that SQLite cannot do in place.

For background see plan
``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``,
section "AppRuntimeDeployment — runtime identity separate from logical
install".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0076_app_runtime_deployments"
down_revision: str | Sequence[str] | None = "0075_invocation_subjects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_col() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON on SQLite — matches the chain convention."""
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "app_runtime_deployments",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "app_id",
            GUID(),
            sa.ForeignKey("marketplace_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "app_version_id",
            GUID(),
            sa.ForeignKey("app_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenancy_model", sa.String(32), nullable=False),
        sa.Column("state_model", sa.String(32), nullable=False),
        sa.Column(
            "runtime_project_id",
            GUID(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("namespace", sa.Text(), nullable=True),
        sa.Column("primary_container_id", sa.Text(), nullable=True),
        sa.Column("volume_id", sa.Text(), nullable=True),
        sa.Column(
            "min_replicas",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_replicas",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "desired_replicas",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "idle_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="600",
        ),
        sa.Column(
            "concurrency_target",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
        sa.Column(
            "scaling_config",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("scaled_to_zero_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_replicas >= min_replicas",
            name="chk_ard_replicas_max_gte_min",
        ),
        sa.CheckConstraint(
            "desired_replicas BETWEEN min_replicas AND max_replicas",
            name="chk_ard_replicas_desired_in_range",
        ),
        sa.CheckConstraint(
            "NOT (state_model = 'per_install_volume' AND max_replicas > 1)",
            name="chk_ard_per_install_volume_max_one",
        ),
        sa.CheckConstraint(
            "NOT (state_model = 'service_pvc' AND max_replicas > 1)",
            name="chk_ard_service_pvc_max_one",
        ),
        sa.CheckConstraint(
            "tenancy_model IN ('per_install', 'shared_singleton', 'per_invocation')",
            name="chk_ard_tenancy",
        ),
        sa.CheckConstraint(
            "state_model IN ('stateless', 'per_install_volume', 'service_pvc', "
            "'shared_volume', 'external')",
            name="chk_ard_state_model",
        ),
    )
    op.create_index(
        "ix_ard_app_id",
        "app_runtime_deployments",
        ["app_id"],
        unique=False,
    )
    op.create_index(
        "ix_ard_runtime_project_id",
        "app_runtime_deployments",
        ["runtime_project_id"],
        unique=False,
    )

    # Attach the deferred FK from app_instances.runtime_deployment_id (column
    # added in 0074_hard_reset_automation_runtime) → app_runtime_deployments.id.
    # ON DELETE SET NULL so deleting a deployment row never destroys install
    # rows; uninstall is the path that clears AppInstance state.
    with op.batch_alter_table("app_instances") as batch_op:
        batch_op.create_foreign_key(
            "fk_app_instances_runtime_deployment_id",
            "app_runtime_deployments",
            ["runtime_deployment_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("app_instances") as batch_op:
        batch_op.drop_constraint(
            "fk_app_instances_runtime_deployment_id",
            type_="foreignkey",
        )

    op.drop_index(
        "ix_ard_runtime_project_id",
        table_name="app_runtime_deployments",
    )
    op.drop_index(
        "ix_ard_app_id",
        table_name="app_runtime_deployments",
    )
    op.drop_table("app_runtime_deployments")
