"""Seed the starter contract templates surfaced by ``ContractTemplates`` UI.

Run inside the backend pod:

    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \\
      python -m scripts.seed_contract_templates

The ``ContractTemplate`` rows are referenced by
``app/src/pages/marketplace/ContractTemplates.tsx`` and pre-fill
``AutomationCreatePage``'s contract editor when the user clicks
"Apply Template". Idempotent — re-running upserts the latest contract for
each named seed without creating duplicates.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import ContractTemplate

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_contract_templates")


# Each entry is the canonical seed row keyed by ``name`` (stable identity).
# ``contract`` lands directly in :class:`AutomationDefinition.contract`
# when the user clicks Apply Template.
SEED_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Web Research",
        "description": (
            "Lightweight research agent: fetches pages and runs web "
            "searches, then posts the digest to the configured destination. "
            "Per-run spend cap keeps spelunking cheap."
        ),
        "category": "research",
        "contract": {
            "allowed_tools": ["web_search", "web_fetch", "send_message"],
            "max_compute_tier": 0,
            "max_iterations": 25,
            "max_spend_per_run_usd": 0.50,
            "on_breach": "pause_for_approval",
        },
    },
    {
        "name": "Code Review",
        "description": (
            "Read-only code reviewer: pulls files for inspection, does "
            "minimal external lookups, and applies the curated 'code-review' "
            "skill. No write tools, no shell — strictly a feedback loop."
        ),
        "category": "coding",
        "contract": {
            "allowed_tools": ["read_file", "web_fetch"],
            "allowed_skills": ["code-review"],
            "max_compute_tier": 0,
            "max_iterations": 15,
            "max_spend_per_run_usd": 0.10,
            "on_breach": "hard_stop",
        },
    },
    {
        "name": "Daily Digest",
        "description": (
            "Cron-friendly summary agent: searches a small surface area, "
            "writes a digest, and ships it to the destination. Cheap "
            "per-run cap is the daily-budget guard."
        ),
        "category": "ops",
        "contract": {
            "allowed_tools": ["send_message", "web_search"],
            "max_compute_tier": 0,
            "max_iterations": 10,
            "max_spend_per_run_usd": 0.05,
            "on_breach": "pause_for_approval",
        },
    },
]


async def _seed_one(db, spec: dict[str, Any]) -> str:
    """Upsert a single template by ``name``. Returns one of: created, updated, skipped."""
    existing = (
        await db.execute(
            select(ContractTemplate).where(ContractTemplate.name == spec["name"])
        )
    ).scalar_one_or_none()

    if existing is None:
        row = ContractTemplate(
            name=spec["name"],
            description=spec.get("description"),
            category=spec.get("category", "general"),
            contract_json=spec["contract"],
            created_by_user_id=None,  # platform-owned seed
            is_published=True,
        )
        db.add(row)
        return "created"

    # Update only if content drift — keep created_at stable.
    drift = (
        existing.description != spec.get("description")
        or existing.category != spec.get("category", "general")
        or existing.contract_json != spec["contract"]
    )
    if not drift:
        return "skipped"
    existing.description = spec.get("description")
    existing.category = spec.get("category", "general")
    existing.contract_json = spec["contract"]
    existing.is_published = True
    return "updated"


async def main() -> int:
    counts = {"created": 0, "updated": 0, "skipped": 0}
    async with AsyncSessionLocal() as db:
        for spec in SEED_TEMPLATES:
            try:
                action = await _seed_one(db, spec)
                counts[action] += 1
                logger.info("template %r -> %s", spec["name"], action)
            except Exception as exc:  # pragma: no cover - operational seed
                logger.exception(
                    "template %r failed: %s", spec.get("name"), exc
                )
                await db.rollback()
                return 1
        await db.commit()
    logger.info(
        "contract template seed done: created=%d updated=%d skipped=%d",
        counts["created"],
        counts["updated"],
        counts["skipped"],
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    sys.exit(asyncio.run(main()))
