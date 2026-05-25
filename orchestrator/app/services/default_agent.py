"""
System Default Agent — code-resident, baked in the backend.

Every user implicitly has the system default agent in their library. The
identity and full config live ONLY in this module — never in user-state
DB rows (no signup-time write, no boot-time per-user sweep).

A single pseudo-row in ``marketplace_agents`` exists at the well-known
sentinel UUID so the FK constraints on ``user_purchased_agents.agent_id``,
``messages.agent_id``, etc. resolve cleanly. That row's contents are
overwritten from the constants below on every boot — code is the source
of truth, the DB row is a referential anchor.

Per-user overrides (model selection, enable/disable toggle) DO use the
existing ``UserPurchasedAgent`` table with ``agent_id = SYSTEM_DEFAULT_AGENT_ID``.
The override row is lazy-created only when the user actually customizes,
so the steady state has zero per-user rows for the default.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Prompt body lives alongside this module so it can be reviewed and edited
# without diff-noise from quoting 10K characters in a Python string literal.
# Read at import time; the boot seeder writes it into the marketplace_agents
# row so the runtime path (chat.py → worker.py → TesslateAgent) reads it
# straight from the DB row like every other agent.
_PROMPT_PATH = Path(__file__).parent / "default_agent_prompt.txt"
try:
    _SYSTEM_DEFAULT_AGENT_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError as exc:
    # If the prompt file is missing the seeder will write NULL, which
    # would crash the runtime on first message (AbstractAgent expects a
    # string). Log loudly so the failure shows up at boot, not at chat
    # time.
    logger.error("default_agent_prompt.txt missing or unreadable: %s", exc)
    _SYSTEM_DEFAULT_AGENT_PROMPT = ""

# ---------------------------------------------------------------------------
# Identity (the only things outside callers should depend on)
# ---------------------------------------------------------------------------

#: Deterministic sentinel UUID. Distinct from 0116's
#: ``00000000-0000-0000-0000-000000000004`` stub (the doctor automation's
#: placeholder); this row is the user-facing system default that every
#: library renders.
SYSTEM_DEFAULT_AGENT_ID: UUID = UUID("00000000-0000-0000-0000-000000000005")

#: Slug is distinct from the federated ``tesslate-agent`` catalog entry —
#: even though the system default's behavior mirrors it. Keeping the
#: slugs separate means upstream catalog drift never touches us.
SYSTEM_DEFAULT_AGENT_SLUG: str = "system-default"

#: The 0116 system-internal source. Re-used here so the row joins cleanly
#: against ``marketplace_sources``.
_SYSTEM_INTERNAL_SOURCE_ID: UUID = UUID("00000000-0000-0000-0000-000000000003")


# ---------------------------------------------------------------------------
# Catalog-row content (the source of truth)
# ---------------------------------------------------------------------------

#: Every field the pseudo-row in ``marketplace_agents`` carries. Boot
#: seeder writes these verbatim. ``None`` means "leave NULL".
SYSTEM_DEFAULT_AGENT_FIELDS: dict[str, object | None] = {
    "name": "System Default Agent",
    "slug": SYSTEM_DEFAULT_AGENT_SLUG,
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
    # AbstractAgent.get_processed_system_prompt() concatenates this with the
    # tool-truthfulness contract; passing None crashes the runtime with
    # ``TypeError: can only concatenate str (not "NoneType") to str``.
    # The prompt body lives in ``default_agent_prompt.txt`` (same
    # directory) and is loaded at module import time.
    "system_prompt": _SYSTEM_DEFAULT_AGENT_PROMPT,
    "mode": "agent",
    "agent_type": "TesslateAgent",
    "tools": None,  # null => TesslateAgent's default registry
    "tool_configs": None,
    "model": "kimi-k2.5",
    "icon": "🤖",
    "pricing_type": "free",
    "price": 0,
    "source_type": "open",
    "is_forkable": False,  # do NOT let users fork the system default
    "is_active": True,
    # is_system=False so the /my-agents listing's ``is_system.isnot(True)``
    # filter does NOT exclude this row. The 0116 doctor stub uses
    # is_system=True specifically to be hidden from user-facing listings.
    "is_system": False,
    # is_published=False so the public marketplace browse does NOT surface
    # it as just another agent (it's the built-in, not a catalog item).
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
    "required_models": None,
    "tags": ["official", "system", "default"],
}


def is_system_default(agent_id_or_slug: UUID | str | None) -> bool:
    """True iff the argument identifies the system default agent.

    Accepts a raw UUID, a string-form UUID, or the slug. Used by lookup
    sites that want to skip extra DB work (the pseudo-row resolution is
    already handled by the regular catalog query; this helper is here
    for future special-casing if we ever decide we want it).
    """
    if agent_id_or_slug is None:
        return False
    if isinstance(agent_id_or_slug, UUID):
        return agent_id_or_slug == SYSTEM_DEFAULT_AGENT_ID
    s = str(agent_id_or_slug)
    if s == SYSTEM_DEFAULT_AGENT_SLUG:
        return True
    try:
        return UUID(s) == SYSTEM_DEFAULT_AGENT_ID
    except (ValueError, TypeError):
        return False


def get_system_default_listing_dict(
    *,
    is_enabled: bool = True,
    selected_model: str | None = None,
    purchase_date: datetime | None = None,
) -> dict[str, object]:
    """Return the system default in the same dict shape as ``/my-agents``.

    The override fields (``is_enabled``, ``selected_model``) reflect the
    user's ``UserPurchasedAgent`` row if one exists, or sensible defaults
    if not.
    """
    fields = SYSTEM_DEFAULT_AGENT_FIELDS
    return {
        "id": str(SYSTEM_DEFAULT_AGENT_ID),
        "name": fields["name"],
        "slug": fields["slug"],
        "description": fields["description"],
        "category": fields["category"],
        "mode": fields["mode"],
        "agent_type": fields["agent_type"],
        "model": fields["model"],
        "selected_model": selected_model,
        "source_type": fields["source_type"],
        "is_forkable": fields["is_forkable"],
        "system_prompt": fields["system_prompt"],
        "icon": fields["icon"],
        "avatar_url": None,
        "pricing_type": fields["pricing_type"],
        "features": fields["features"],
        "tools": fields["tools"],
        "tool_configs": fields["tool_configs"],
        "purchase_date": (purchase_date or datetime.now(UTC)).isoformat(),
        "purchase_type": "system_default",
        "expires_at": None,
        "is_custom": False,
        "parent_agent_id": None,
        "is_enabled": is_enabled,
        "is_published": False,  # browse listing already hides it; consistent here
        "usage_count": 0,
        "creator_type": "official",
        "creator_name": "Tesslate",
        "creator_username": None,
        "creator_avatar_url": None,
        "created_by_user_id": None,
        "forked_by_user_id": None,
        # The frontend filter is `is_enabled && !is_admin_disabled && !is_system`.
        # All three must allow it through.
        "is_admin_disabled": False,
        "is_system": False,
    }


# ---------------------------------------------------------------------------
# Idempotent boot seeder
# ---------------------------------------------------------------------------


async def seed_system_default_agent(db: AsyncSession) -> bool:
    """Plant (or refresh) the pseudo-row backing the system default agent.

    Returns ``True`` if a write happened (insert or update), ``False`` on
    a no-op refresh. Idempotent — safe at every boot. Uses a single
    upsert keyed by ``id``: the row's columns are unconditionally rewritten
    from :data:`SYSTEM_DEFAULT_AGENT_FIELDS` so any out-of-band mutation
    (e.g. via an admin tool) is reverted on the next deploy. Code is the
    source of truth, the DB row is a referential anchor.

    Postgres-only. The matching alembic migration runs the same INSERT
    on first upgrade so this seed is a safety-net for restored DBs and
    a "rewrite on every boot" channel for config changes.
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    dialect_name = getattr(bind, "dialect", None) and bind.dialect.name
    if dialect_name == "sqlite":
        # Desktop runs on SQLite. The schema is the same; we still want
        # the row present. Use a portable form of the upsert.
        await db.execute(
            text(
                """
                INSERT INTO marketplace_agents (
                    id, name, slug, description, long_description, category,
                    item_type, system_prompt, mode, agent_type, tools,
                    tool_configs, model, icon, pricing_type, price,
                    source_type, is_forkable, is_active, is_system,
                    is_published, is_featured, requires_user_keys,
                    features, required_models, tags, source_id,
                    created_at, updated_at
                )
                VALUES (
                    :id, :name, :slug, :description, :long_description,
                    :category, :item_type, :system_prompt, :mode, :agent_type,
                    :tools, :tool_configs, :model, :icon, :pricing_type,
                    :price, :source_type, :is_forkable, :is_active,
                    :is_system, :is_published, :is_featured,
                    :requires_user_keys, :features, :required_models, :tags,
                    :source_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    long_description = excluded.long_description,
                    category = excluded.category,
                    system_prompt = excluded.system_prompt,
                    mode = excluded.mode,
                    agent_type = excluded.agent_type,
                    tools = excluded.tools,
                    tool_configs = excluded.tool_configs,
                    model = excluded.model,
                    icon = excluded.icon,
                    pricing_type = excluded.pricing_type,
                    price = excluded.price,
                    source_type = excluded.source_type,
                    is_forkable = excluded.is_forkable,
                    is_active = excluded.is_active,
                    is_system = excluded.is_system,
                    is_published = excluded.is_published,
                    is_featured = excluded.is_featured,
                    requires_user_keys = excluded.requires_user_keys,
                    features = excluded.features,
                    required_models = excluded.required_models,
                    tags = excluded.tags,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            _seed_params(),
        )
        await db.commit()
        logger.info("System default agent seeded (sqlite)")
        return True

    # Postgres (cloud / minikube).
    await db.execute(
        text(
            """
            INSERT INTO marketplace_agents (
                id, name, slug, description, long_description, category,
                item_type, system_prompt, mode, agent_type, tools,
                tool_configs, model, icon, pricing_type, price,
                source_type, is_forkable, is_active, is_system,
                is_published, is_featured, requires_user_keys,
                features, required_models, tags, source_id,
                created_at, updated_at
            )
            VALUES (
                :id, :name, :slug, :description, :long_description,
                :category, :item_type, CAST(:system_prompt AS TEXT),
                :mode, :agent_type, CAST(:tools AS JSON),
                CAST(:tool_configs AS JSON), :model, :icon, :pricing_type,
                :price, :source_type, :is_forkable, :is_active,
                :is_system, :is_published, :is_featured,
                :requires_user_keys, CAST(:features AS JSON),
                CAST(:required_models AS JSON), CAST(:tags AS JSON),
                :source_id, NOW(), NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                long_description = EXCLUDED.long_description,
                category = EXCLUDED.category,
                system_prompt = EXCLUDED.system_prompt,
                mode = EXCLUDED.mode,
                agent_type = EXCLUDED.agent_type,
                tools = EXCLUDED.tools,
                tool_configs = EXCLUDED.tool_configs,
                model = EXCLUDED.model,
                icon = EXCLUDED.icon,
                pricing_type = EXCLUDED.pricing_type,
                price = EXCLUDED.price,
                source_type = EXCLUDED.source_type,
                is_forkable = EXCLUDED.is_forkable,
                is_active = EXCLUDED.is_active,
                is_system = EXCLUDED.is_system,
                is_published = EXCLUDED.is_published,
                is_featured = EXCLUDED.is_featured,
                requires_user_keys = EXCLUDED.requires_user_keys,
                features = EXCLUDED.features,
                required_models = EXCLUDED.required_models,
                tags = EXCLUDED.tags,
                updated_at = NOW()
            """
        ),
        _seed_params(),
    )
    await db.commit()
    logger.info("System default agent seeded (postgres)")
    return True


def _seed_params() -> dict[str, object | None]:
    """Bind params for the INSERT … ON CONFLICT statement above."""
    import json as _json

    f = SYSTEM_DEFAULT_AGENT_FIELDS

    def _as_json(v: object | None) -> str | None:
        return None if v is None else _json.dumps(v)

    return {
        "id": str(SYSTEM_DEFAULT_AGENT_ID),
        "name": f["name"],
        "slug": f["slug"],
        "description": f["description"],
        "long_description": f["long_description"],
        "category": f["category"],
        "item_type": f["item_type"],
        "system_prompt": f["system_prompt"],
        "mode": f["mode"],
        "agent_type": f["agent_type"],
        "tools": _as_json(f["tools"]),
        "tool_configs": _as_json(f["tool_configs"]),
        "model": f["model"],
        "icon": f["icon"],
        "pricing_type": f["pricing_type"],
        "price": f["price"],
        "source_type": f["source_type"],
        "is_forkable": f["is_forkable"],
        "is_active": f["is_active"],
        "is_system": f["is_system"],
        "is_published": f["is_published"],
        "is_featured": f["is_featured"],
        "requires_user_keys": f["requires_user_keys"],
        "features": _as_json(f["features"]),
        "required_models": _as_json(f["required_models"]),
        "tags": _as_json(f["tags"]),
        "source_id": str(_SYSTEM_INTERNAL_SOURCE_ID),
    }


__all__ = [
    "SYSTEM_DEFAULT_AGENT_ID",
    "SYSTEM_DEFAULT_AGENT_SLUG",
    "SYSTEM_DEFAULT_AGENT_FIELDS",
    "is_system_default",
    "get_system_default_listing_dict",
    "seed_system_default_agent",
]
