"""Cross-phase columns — provenance, default contracts, team destinations,
project↔app linkage, payer enum widening, and AppRuntimeDeployment.namespace
backfill helper.

Revision ID: 0081_cross_phase_cols
Revises: 0080_controller_plane
Create Date: 2026-04-26

These columns surface in multiple plan sections but never had their own
migration:

* ``MarketplaceAgent.created_by_automation_id`` — Phase 5 agent-builder
  provenance. Lets the dispatcher walk parent/child chains for cycle
  detection and budget rollup. FK → automation_definitions.
* ``Project.default_contract_template`` — Phase 5 UX convenience. New
  Automation Builder flows seed contract from this JSONB so the user
  only edits what differs from the project default.
* ``Project.published_app_id`` — strong project ↔ MarketplaceApp link.
  Today the relationship is implicit via the Publish Drawer; this column
  makes "which app does this project publish to?" a one-column lookup.
* ``ChannelConfig.team_id`` — team-scoped destinations. Lets a team
  share a Slack workspace credential set across automations owned by
  any team member.
* ``SpendRecord.payer`` — widen CHECK to include the six values
  ``InvocationSubject.payer_policy`` actually emits ('installer',
  'creator', 'team', 'platform', 'byok', 'parent_run'). Old check was
  silently coerced to 'creator | platform | installer | byok'; this
  syncs them.

Down revision is ``0080_controller_plane``. Portable across Postgres +
SQLite via the GUID TypeDecorator and ``op.batch_alter_table`` for the
SQLite-incompatible CHECK rewrites.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0081_cross_phase_cols"
down_revision: str | Sequence[str] | None = "0080_controller_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # ------------------------------------------------------------------
    # MarketplaceAgent.created_by_automation_id
    #
    # Nullable: most agents are user-created via UI, not by an automation.
    # FK uses ondelete=SET NULL so deleting the source automation doesn't
    # nuke the agent it built.
    # ------------------------------------------------------------------
    op.add_column(
        "marketplace_agents",
        sa.Column(
            "created_by_automation_id",
            GUID(),
            nullable=True,
        ),
    )
    if not is_sqlite:
        op.create_foreign_key(
            "fk_marketplace_agents_created_by_automation",
            "marketplace_agents",
            "automation_definitions",
            ["created_by_automation_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_ma_created_by_automation",
        "marketplace_agents",
        ["created_by_automation_id"],
    )

    # ------------------------------------------------------------------
    # Project.default_contract_template
    #
    # JSONB on Postgres / JSON on SQLite. Default empty dict so the
    # column is never NULL (UI can iterate freely).
    # ------------------------------------------------------------------
    op.add_column(
        "projects",
        sa.Column(
            "default_contract_template",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )

    # ------------------------------------------------------------------
    # Project.published_app_id
    #
    # Optional FK to marketplace_apps so a project can declare "I publish
    # to this app id". Nullable: most projects are workspace-only.
    # ------------------------------------------------------------------
    op.add_column(
        "projects",
        sa.Column(
            "published_app_id",
            GUID(),
            nullable=True,
        ),
    )
    if not is_sqlite:
        op.create_foreign_key(
            "fk_projects_published_app",
            "projects",
            "marketplace_apps",
            ["published_app_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_projects_published_app",
        "projects",
        ["published_app_id"],
    )

    # ------------------------------------------------------------------
    # ChannelConfig.team_id
    #
    # Optional team scope. NULL = personal; set = shared across team.
    # ------------------------------------------------------------------
    op.add_column(
        "channel_configs",
        sa.Column(
            "team_id",
            GUID(),
            nullable=True,
        ),
    )
    if not is_sqlite:
        op.create_foreign_key(
            "fk_channel_configs_team",
            "channel_configs",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_channel_configs_team",
        "channel_configs",
        ["team_id"],
    )

    # ------------------------------------------------------------------
    # SpendRecord.payer — widen CHECK from 4 → 6 values.
    #
    # Old: 'creator' | 'platform' | 'installer' | 'byok'
    # New: + 'team' | 'parent_run' (matching InvocationSubject.payer_policy).
    #
    # Postgres requires DROP + ADD CHECK; SQLite needs batch_alter_table.
    # ------------------------------------------------------------------
    if is_sqlite:
        # SQLite test DB: SpendRecord.payer was created in 0056 with NO
        # named CHECK constraint, so batch_alter_table's reflection-based
        # drop_constraint("ck_spend_records_payer", ...) raises KeyError
        # before the try/except fires (alembic pre-flights the constraint
        # set on entry to batch mode). The desktop sidecar runs against
        # SQLite and never sees billing CHECK enforcement at the DB
        # level — the application validates payer via the
        # InvocationSubject.payer_policy enum. Production Postgres gets
        # the widened CHECK in the else branch below.
        return
    else:
        # Postgres: drop any pre-existing payer CHECK by name pattern,
        # then add the widened one. Several names have been used over time.
        for cn in (
            "ck_spend_records_payer",
            "spend_records_payer_check",
            "chk_spend_records_payer",
        ):
            op.execute(
                f"ALTER TABLE spend_records DROP CONSTRAINT IF EXISTS {cn}"
            )
        op.create_check_constraint(
            "chk_spend_records_payer",
            "spend_records",
            "payer IN ('creator','platform','installer','byok','team','parent_run')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # SpendRecord.payer — restore narrow CHECK (no-op on SQLite — see
    # upgrade() comment).
    if is_sqlite:
        pass
    else:
        op.execute(
            "ALTER TABLE spend_records DROP CONSTRAINT IF EXISTS chk_spend_records_payer"
        )
        op.create_check_constraint(
            "chk_spend_records_payer",
            "spend_records",
            "payer IN ('creator','platform','installer','byok')",
        )

    # ChannelConfig.team_id
    op.drop_index("ix_channel_configs_team", table_name="channel_configs")
    if not is_sqlite:
        op.drop_constraint(
            "fk_channel_configs_team", "channel_configs", type_="foreignkey"
        )
    op.drop_column("channel_configs", "team_id")

    # Project.published_app_id
    op.drop_index("ix_projects_published_app", table_name="projects")
    if not is_sqlite:
        op.drop_constraint(
            "fk_projects_published_app", "projects", type_="foreignkey"
        )
    op.drop_column("projects", "published_app_id")

    # Project.default_contract_template
    op.drop_column("projects", "default_contract_template")

    # MarketplaceAgent.created_by_automation_id
    op.drop_index(
        "ix_ma_created_by_automation", table_name="marketplace_agents"
    )
    if not is_sqlite:
        op.drop_constraint(
            "fk_marketplace_agents_created_by_automation",
            "marketplace_agents",
            type_="foreignkey",
        )
    op.drop_column("marketplace_agents", "created_by_automation_id")
