"""Seed the user-facing System Default Agent pseudo-row.

Revision ID: 0121_seed_system_default_agent
Revises: 0120_wsdata_collection_schema
Create Date: 2026-05-25

Plants ONE row in ``marketplace_agents`` at the well-known sentinel
``00000000-0000-0000-0000-000000000005`` (distinct from 0116's
``…0004`` doctor stub). That row is the FK target for any user-state
write that references the system default — its content is rewritten
from ``app.services.default_agent.SYSTEM_DEFAULT_AGENT_FIELDS`` on
every boot, so code is the source of truth.

Idempotent: ``ON CONFLICT (id) DO NOTHING``. Re-running this migration
on a DB that already has the boot seeder's row is a no-op.

Postgres only — desktop (sqlite) seeds the row via the boot seeder
exclusively.
"""

from __future__ import annotations

import json
from uuid import UUID

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0121_seed_system_default_agent"
down_revision = "0120_wsdata_collection_schema"
branch_labels = None
depends_on = None

# Mirrors app.services.default_agent. Duplicated here so the migration
# is self-contained and can run before the application is importable.
SYSTEM_DEFAULT_AGENT_ID = UUID("00000000-0000-0000-0000-000000000005")
SYSTEM_INTERNAL_SOURCE_ID = UUID("00000000-0000-0000-0000-000000000003")

_FIELDS: dict[str, object] = {
    "name": "System Default Agent",
    "slug": "system-default",
    "description": "The built-in coding assistant. Always available to every user.",
    "long_description": (
        "OpenSail's general-purpose autonomous coding agent. Reads, writes, "
        "and patches files; executes shell commands; plans multi-step tasks; "
        "delegates to specialist sub-agents. Backed by the TesslateAgent "
        "runtime — same engine the Tesslate Agent uses, baked into the "
        "platform so every user has it from the first login."
    ),
    "category": "fullstack",
    "item_type": "agent",
    "mode": "agent",
    "agent_type": "TesslateAgent",
    "model": "kimi-k2.5",
    "icon": "🤖",
    "pricing_type": "free",
    "price": 0,
    "source_type": "open",
    "is_forkable": False,
    "is_active": True,
    "is_system": False,
    "is_published": False,
    "is_featured": False,
    "requires_user_keys": False,
    "features": [
        "Always-on default",
        "Autonomous coding",
        "Multi-step planning",
        "File operations",
        "Command execution",
        "Subagent delegation",
    ],
    "tags": ["official", "system", "default"],
}


def _load_prompt() -> str:
    """Load the system prompt from the canonical text file.

    The migration writes the prompt into the row's ``system_prompt``
    column on first deploy so the runtime path
    (``TesslateAgent`` -> ``AbstractAgent.get_processed_system_prompt``)
    can do its string concat without crashing. The boot seeder
    re-asserts the same content from
    ``services.default_agent.SYSTEM_DEFAULT_AGENT_FIELDS`` on every
    restart — code is the source of truth.

    Importing from the app at migration time is the existing pattern
    (see 0116 importing ``app.types.guid``).
    """
    try:
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[2] / "app" / "services" / "default_agent_prompt.txt"
        ).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - migration safety
        # Surfacing as a non-empty placeholder is safer than NULL: the
        # row exists, FKs satisfy, but the agent will return a noisy
        # error on first message instead of a runtime crash.
        return (
            "System default agent prompt file is missing on this deploy "
            f"({exc!r}). Boot seeder will overwrite on next restart."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Desktop runs sqlite — the boot seeder plants this row instead.
        return

    prompt = _load_prompt()

    # The 0116 system-internal source must exist (we depend on its UUID
    # for source_id). 0116 is in our dependency chain, so it's guaranteed
    # to have run before this migration.
    bind.execute(
        text(
            """
            INSERT INTO marketplace_agents (
                id, name, slug, description, long_description, category,
                item_type, system_prompt, mode, agent_type, model, icon,
                pricing_type, price, source_type, is_forkable, is_active,
                is_system, is_published, is_featured, requires_user_keys,
                features, tags, source_id, created_at, updated_at
            )
            VALUES (
                :id, :name, :slug, :description, :long_description,
                :category, :item_type, :system_prompt, :mode, :agent_type,
                :model, :icon, :pricing_type, :price, :source_type,
                :is_forkable, :is_active, :is_system, :is_published,
                :is_featured, :requires_user_keys, CAST(:features AS JSON),
                CAST(:tags AS JSON), :source_id, NOW(), NOW()
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": str(SYSTEM_DEFAULT_AGENT_ID),
            "source_id": str(SYSTEM_INTERNAL_SOURCE_ID),
            "name": _FIELDS["name"],
            "slug": _FIELDS["slug"],
            "description": _FIELDS["description"],
            "long_description": _FIELDS["long_description"],
            "category": _FIELDS["category"],
            "item_type": _FIELDS["item_type"],
            "system_prompt": prompt,
            "mode": _FIELDS["mode"],
            "agent_type": _FIELDS["agent_type"],
            "model": _FIELDS["model"],
            "icon": _FIELDS["icon"],
            "pricing_type": _FIELDS["pricing_type"],
            "price": _FIELDS["price"],
            "source_type": _FIELDS["source_type"],
            "is_forkable": _FIELDS["is_forkable"],
            "is_active": _FIELDS["is_active"],
            "is_system": _FIELDS["is_system"],
            "is_published": _FIELDS["is_published"],
            "is_featured": _FIELDS["is_featured"],
            "requires_user_keys": _FIELDS["requires_user_keys"],
            "features": json.dumps(_FIELDS["features"]),
            "tags": json.dumps(_FIELDS["tags"]),
        },
    )


def downgrade() -> None:
    # Removing the pseudo-row would orphan any per-user override rows
    # (UserPurchasedAgent FK has CASCADE on delete, so they'd be wiped).
    # Treat this as a one-way migration — downgrades require explicit
    # operator intervention.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        text("DELETE FROM marketplace_agents WHERE id = :id"),
        {"id": str(SYSTEM_DEFAULT_AGENT_ID)},
    )
