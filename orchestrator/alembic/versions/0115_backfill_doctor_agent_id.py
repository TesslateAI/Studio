"""Backfill agent_id into existing doctor agent.run actions.

Revision ID: 0115_backfill_doctor_agent_id
Revises: 0114_backfill_typed_secrets
Create Date: 2026-05-18

Develop's #469 / TC-03 commit added a Pydantic validator on
``AutomationActionIn`` that requires ``agent.run`` actions to declare
``config.agent_id``. Pre-existing G5 doctor rows (created before the
adapter refactor that started supplying agent_id at creation) have
``agent.run`` actions whose config carries only ``prompt`` and
``target_automation_id`` — no ``agent_id``. The router's response
projection runs every row through ``AutomationActionOut.model_validate``
on read, so those rows now 500 on ``GET /api/automations/{id}``.

This migration fills in a default ``agent_id`` for affected actions
using the same "pick any runnable agent in the owner's library or a
system agent" heuristic that the runtime helper now uses for fresh
doctors. Idempotent: only touches actions where ``config.agent_id``
is null/empty/missing.

Rows we can't backfill (owner has no library agent + no system agent
exists) are left as-is and logged — the user can fix by installing
an agent and re-saving the doctor via the UI or by running this
migration again after install.

Postgres-only path uses ``jsonb_set``; SQLite skipped (test fixture
builds fresh schemas).
"""

import logging

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0115_backfill_doctor_agent_id"
down_revision = "0114_backfill_typed_secrets"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.migration.0115")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Find every agent.run action lacking config.agent_id, joined to its
    # automation so we know the owner. We DON'T restrict to doctor rows
    # (parent_automation_id IS NOT NULL) — any older user-authored
    # row in this state has the same problem and benefits from the fix.
    targets = bind.execute(
        text(
            """
            SELECT
                a.id AS action_id,
                d.id AS automation_id,
                d.owner_user_id AS owner_user_id
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
        return

    # Resolver: prefer a system agent (works for everyone); else the
    # owner's first library agent. Looked up per-owner because the
    # owner's library is what bounds visibility.
    system_agent_id = bind.execute(
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

    fixed = 0
    skipped = 0
    for action_id, automation_id, owner_user_id in targets:
        chosen_id = system_agent_id
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
                "0115: action %s on automation %s has no library agent for "
                "owner %s; left as-is — user must install one and re-save",
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
        "0115: backfilled agent_id on %s agent.run action(s); skipped %s "
        "(owner had no library agent + no system agent available)",
        fixed,
        skipped,
    )


def downgrade() -> None:
    # No-op: we can't reliably distinguish backfilled values from
    # user-supplied ones, so we leave the column populated. Re-applying
    # the migration after a manual rollback is idempotent.
    return
