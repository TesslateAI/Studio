"""InvocationSubject — unified billing + token identity (Phase 2).

Revision ID: 0075_invocation_subjects
Revises: 0074_hard_reset
Create Date: 2026-04-26

Phase 2 of the OpenSail Automation Runtime rollout.

Creates the ``invocation_subjects`` table — a single resolved billing +
token identity row attached to every ``AutomationRun``. This collapses
three separate code paths (``wallet_mix`` for apps, ``credit_service``
for user OpenSail credits, ``key_lifecycle`` for LiteLLM keys) into one
authoritative decision. After this lands every ``SpendRecord`` and
``LiteLLMKeyLedger`` row carries ``invocation_subject_id`` so the manager
dashboard query "spend by app per user in March" is a single GROUP BY.

What this migration does:

1. Creates ``invocation_subjects`` (id, automation_run_id, invoking_user_id,
   team_id, app_instance_id, app_action_id, agent_id, payer_policy,
   parent_run_id, credit_source, credit_source_ref, budget_envelope,
   spent_so_far_usd, litellm_key_id, created_at) with two CHECK
   constraints on the enum-like string columns.
2. Adds the deferred FK from ``spend_records.invocation_subject_id`` to
   ``invocation_subjects.id``. The column itself was added in
   ``0073_spend_attribution`` (Phase 0); only the constraint lands here.
3. Adds a new ``litellm_key_ledger.invocation_subject_id`` column plus
   FK to ``invocation_subjects.id``. The column is brand new — Phase 0
   only touched ``spend_records``.

All FKs use ``ON DELETE SET NULL`` so destroying an ``invocation_subjects``
row never orphans (or destroys) the spend rows that referenced it — the
billing trail is preserved as a NULL pointer plus the existing
``payer_user_id`` / ``app_instance_id`` columns on ``spend_records``.

Backward compat: existing ``spend_records`` rows from before Phase 2
have ``invocation_subject_id=NULL`` and stay that way (no backfill).

Portable across Postgres (cloud) and SQLite (desktop sidecar) via
``op.batch_alter_table`` for the FK alters that SQLite cannot do in
place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0075_invocation_subjects"
down_revision: str | Sequence[str] | None = "0074_hard_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_col() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON on SQLite — matches the chain convention."""
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "invocation_subjects",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column(
            "automation_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "invoking_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "app_instance_id",
            GUID(),
            sa.ForeignKey("app_instances.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "app_action_id",
            GUID(),
            sa.ForeignKey("app_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            GUID(),
            sa.ForeignKey("marketplace_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payer_policy", sa.String(32), nullable=False),
        sa.Column(
            "parent_run_id",
            GUID(),
            sa.ForeignKey("automation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("credit_source", sa.String(48), nullable=False),
        sa.Column("credit_source_ref", sa.Text(), nullable=True),
        sa.Column(
            "budget_envelope",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "spent_so_far_usd",
            sa.Numeric(12, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column("litellm_key_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "payer_policy IN ('installer', 'creator', 'team', 'platform', "
            "'byok', 'parent_run')",
            name="ck_invocation_subjects_payer_policy",
        ),
        sa.CheckConstraint(
            "credit_source IN ('opensail_credits', 'scoped_litellm_key', "
            "'byok_litellm_key', 'creator_wallet', 'team_credits', "
            "'platform_budget', 'parent_run')",
            name="ck_invocation_subjects_credit_source",
        ),
    )
    op.create_index(
        "ix_invocation_subjects_automation_run_id",
        "invocation_subjects",
        ["automation_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_invocation_subjects_invoking_user_id",
        "invocation_subjects",
        ["invoking_user_id"],
        unique=False,
    )

    # Attach the deferred FK from spend_records.invocation_subject_id (column
    # added in 0073_spend_attribution) → invocation_subjects.id.
    with op.batch_alter_table("spend_records") as batch_op:
        batch_op.create_foreign_key(
            "fk_spend_records_invocation_subject_id",
            "invocation_subjects",
            ["invocation_subject_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Add invocation_subject_id to litellm_key_ledger and FK it.
    with op.batch_alter_table("litellm_key_ledger") as batch_op:
        batch_op.add_column(
            sa.Column("invocation_subject_id", GUID(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_litellm_key_ledger_invocation_subject_id",
            "invocation_subjects",
            ["invocation_subject_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("litellm_key_ledger") as batch_op:
        batch_op.drop_constraint(
            "fk_litellm_key_ledger_invocation_subject_id",
            type_="foreignkey",
        )
        batch_op.drop_column("invocation_subject_id")

    with op.batch_alter_table("spend_records") as batch_op:
        batch_op.drop_constraint(
            "fk_spend_records_invocation_subject_id",
            type_="foreignkey",
        )

    op.drop_index(
        "ix_invocation_subjects_invoking_user_id",
        table_name="invocation_subjects",
    )
    op.drop_index(
        "ix_invocation_subjects_automation_run_id",
        table_name="invocation_subjects",
    )
    op.drop_table("invocation_subjects")
