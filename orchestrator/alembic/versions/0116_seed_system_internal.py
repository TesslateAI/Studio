"""Seed system-internal marketplace source + stub agent, re-run doctor backfill.

Revision ID: 0116_seed_system_internal
Revises: 0115_backfill_doctor_agent_id
Create Date: 2026-05-18

Migration 0115 backfilled ``automation_actions.config.agent_id`` for
agent.run rows missing it. The resolver preferred a system agent
(``is_system=True``); failing that, the owner's first library agent.
In tenants that have neither (fresh minikube, OSS users with no
seeded system agents and no purchased agents), 0115 logged warnings
and left those rows untouched — so doctor automations still 500 on
detail GET under develop's TC-03 validator.

This migration unblocks all of them by planting a guaranteed-present
system agent:

1. Insert a dedicated ``system-internal`` marketplace source
   (deterministic id ``00…003``). Chosen so the row is NEVER
   reaped by either sync path:
     - ``sync_local`` filters on ``handle='local'`` (we're 'system-internal')
     - ``sync_all_active_sources`` excludes ``trust_level='local'`` AND
       ``base_url`` starting with ``local://`` (we are both)
   The source is hidden from end users — it has no manifest to scan,
   no remote endpoint, and exists solely to anchor platform-owned rows.

2. Insert a ``system-default-agent`` row under that source with
   ``is_system=True``. Hidden from public marketplace listings
   (``routers/marketplace.py`` excludes is_system) and from
   user-library views (``list_user_resources`` does the same). The
   ``resolve_agent_in_user_scope`` resolver grants every authenticated
   user access via the is_system bypass, so doctors owned by any user
   can bind it without a per-user library install.

3. Re-run the 0115 backfill SQL. Idempotent — only touches agent.run
   rows where ``config.agent_id`` is still NULL/missing. After 0116
   that set should resolve to zero rows post-update.

The stub agent has the bare-minimum schema to satisfy NOT NULL
constraints + the TC-03 ``config.agent_id`` validator. It is NOT
expected to power production doctor runs (no real ``system_prompt``,
``model``, or ``tools``); the marketplace seed pipeline replaces it
with a fully-configured default. Read-path correctness — letting
detail pages render — is what 0116 buys.

Postgres-only path; SQLite-backed tests build fresh schemas via
``Base.metadata.create_all`` and don't go through alembic.
"""

import logging
from uuid import UUID

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0116_seed_system_internal"
down_revision = "0115_backfill_doctor_agent_id"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.migration.0116")

# Deterministic UUIDs so this migration is replay-safe and the rows
# can be referenced from later code without a lookup. The system
# source follows the 0088 pattern (``00…001`` = tesslate-official,
# ``00…002`` = local, ``00…003`` = system-internal).
SYSTEM_INTERNAL_SOURCE_ID = UUID("00000000-0000-0000-0000-000000000003")
SYSTEM_DEFAULT_AGENT_ID = UUID("00000000-0000-0000-0000-000000000004")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. Plant the system-internal source (idempotent on id).
    bind.execute(
        text(
            """
            INSERT INTO marketplace_sources
                (id, handle, display_name, base_url, scope, trust_level, is_active)
            VALUES
                (:id, 'system-internal', 'System (internal)',
                 'local://internal', 'system', 'local', true)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": str(SYSTEM_INTERNAL_SOURCE_ID)},
    )

    # 2. Plant the stub system agent under that source. Slug uniqueness
    #    is per-source (``uq_marketplace_agents_source_slug``) so this
    #    won't collide with any user-created 'system-default-agent'
    #    elsewhere. Deterministic id keeps the row referenceable.
    bind.execute(
        text(
            """
            INSERT INTO marketplace_agents
                (id, name, slug, description, category, item_type,
                 is_active, is_system, pricing_type, source_id, icon)
            VALUES
                (:id, 'System default agent', 'system-default-agent',
                 'Platform-owned stub agent used as a default binding for '
                 'internal automations (e.g. the per-workflow doctor). '
                 'Replace with a fully-configured default via your '
                 'marketplace seeds when shipping doctors into production.',
                 'builder', 'agent', true, true, 'free', :source_id, '🩺')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": str(SYSTEM_DEFAULT_AGENT_ID),
            "source_id": str(SYSTEM_INTERNAL_SOURCE_ID),
        },
    )

    # 3. Re-run 0115's backfill against any remaining null-agent_id rows.
    #    With the stub guaranteed present this UPDATE now resolves to zero
    #    survivors on the next read.
    targets = bind.execute(
        text(
            """
            SELECT a.id, d.id AS automation_id, d.owner_user_id
            FROM automation_actions a
            JOIN automation_definitions d ON d.id = a.automation_id
            WHERE a.action_type = 'agent.run'
              AND (
                a.config->>'agent_id' IS NULL
                OR a.config->>'agent_id' = ''
              )
            """
        )
    ).fetchall()

    if not targets:
        logger.info("0116: no agent.run rows missing agent_id — nothing to backfill")
        return

    # Resolver: same preference order as 0115 + the live doctor.py.
    # The stub we just planted satisfies branch 1 for every owner, so the
    # owner-library fallback path is unreachable here unless an op deletes
    # the stub — kept for completeness / future env drift.
    fixed = 0
    skipped = 0
    for action_id, automation_id, owner_user_id in targets:
        chosen_id = bind.execute(
            text(
                """
                SELECT id FROM marketplace_agents
                WHERE item_type = 'agent'
                  AND is_active = true
                  AND is_system = true
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
        ).scalar_one_or_none()
        if chosen_id is None:
            chosen_id = bind.execute(
                text(
                    """
                    SELECT ma.id
                    FROM marketplace_agents ma
                    JOIN user_purchased_agents upa ON upa.agent_id = ma.id
                    WHERE ma.item_type = 'agent'
                      AND ma.is_active = true
                      AND upa.user_id = :owner_id
                    ORDER BY ma.created_at ASC
                    LIMIT 1
                    """
                ),
                {"owner_id": owner_user_id},
            ).scalar_one_or_none()
        if chosen_id is None:
            logger.warning(
                "0116: action %s on automation %s — no agent available for owner %s",
                action_id,
                automation_id,
                owner_user_id,
            )
            skipped += 1
            continue

        bind.execute(
            text(
                """
                UPDATE automation_actions
                SET config = jsonb_set(
                    COALESCE(config, '{}'::jsonb),
                    '{agent_id}',
                    to_jsonb(CAST(:agent_id AS text)),
                    true
                )
                WHERE id = :action_id
                """
            ),
            {"agent_id": str(chosen_id), "action_id": action_id},
        )
        fixed += 1

    logger.info(
        "0116: backfilled agent_id on %s agent.run action(s); skipped %s",
        fixed,
        skipped,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Drop the stub agent IFF it hasn't been replaced by anything pointing
    # at it. We leave the source row in place — future internal automations
    # may already depend on its id; a one-row source costs nothing.
    bind.execute(
        text(
            """
            DELETE FROM marketplace_agents
            WHERE id = :id
              AND NOT EXISTS (
                SELECT 1 FROM automation_actions
                WHERE config->>'agent_id' = :id_text
              )
            """
        ),
        {
            "id": str(SYSTEM_DEFAULT_AGENT_ID),
            "id_text": str(SYSTEM_DEFAULT_AGENT_ID),
        },
    )
