"""
Idempotent provisioner for the canonical "Tesslate" User row.

After Wave 10 the catalog itself is no longer seeded inside the orchestrator
— the federation sync worker pulls rows from the marketplace service and
tags them with ``source_id == TESSLATE_OFFICIAL_ID``. The Tesslate User row
remains as the historical owner identity that legacy ``MarketplaceAgent``
rows reference via ``created_by_user_id`` (Wave 4 routes branding through
``source.trust_level == 'official'`` instead, but the FK is still in place
to keep schema constraints valid and to attribute deployment-target seed
rows to a real user).

Lives under ``services/`` (not ``seeds/``) because it is depended on by
non-seed call sites — the deployment_targets seeder, the federation sync
worker (when it provisions ``created_by_user_id`` for synced rows), and any
future code that needs a deterministic owner for system-managed catalog
content.

The canonical identity is a single row keyed by email
``official@tesslate.com``; idempotent UPSERT semantics — re-running on a
healthy DB is a no-op.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models_auth import User

logger = logging.getLogger(__name__)


# Authoritative Tesslate User row spec. Every field that lands on the row is
# listed here so callers can re-assert mutable branding fields on every boot.
TESSLATE_ACCOUNT: dict[str, object] = {
    "email": "official@tesslate.com",
    "username": "tesslate",
    "name": "Tesslate",
    "slug": "tesslate",
    "bio": "Official Tesslate account. Building the future of AI-powered development.",
    "twitter_handle": "tesslateai",
    "github_username": "TesslateAI",
    "website_url": "https://tesslate.com",
    "avatar_url": "https://avatars.githubusercontent.com/u/189477337",
    "is_superuser": True,
    "is_verified": True,
}


async def get_or_create_tesslate_account(db: AsyncSession) -> User:
    """Return the canonical Tesslate ``User`` row, creating it if missing.

    The caller owns the surrounding transaction commit only when the row is
    found (no writes performed). When the row is created, this function
    issues its own commit so the freshly-minted ID is durable before the
    caller starts inserting FK-bearing rows that reference it.
    """
    result = await db.execute(select(User).where(User.email == TESSLATE_ACCOUNT["email"]))
    tesslate_user = result.scalar_one_or_none()

    if not tesslate_user:
        logger.info("Creating Tesslate official account...")
        tesslate_user = User(
            id=uuid4(),
            hashed_password="disabled",
            is_active=True,
            **TESSLATE_ACCOUNT,
        )
        db.add(tesslate_user)
        await db.commit()
        await db.refresh(tesslate_user)
        logger.info("Created Tesslate account (ID: %s)", tesslate_user.id)
    else:
        logger.debug("Tesslate account exists (ID: %s)", tesslate_user.id)

    return tesslate_user


__all__ = ["TESSLATE_ACCOUNT", "get_or_create_tesslate_account"]
