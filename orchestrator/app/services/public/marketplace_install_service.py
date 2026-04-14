"""
Marketplace install service — resolves items, enforces paid-item gates,
records installs, and returns download URLs for the desktop client.

`item_type` domain:
- `agent`, `skill`, `mcp_server` → `MarketplaceAgent` (filtered by `item_type`)
- `base`                         → `MarketplaceBase`

Paid gates: free items are recorded as a `UserPurchasedAgent`/`UserPurchasedBase`
row with `purchase_type="free"` on first install. Paid items require an active
purchase row already (created by the existing Stripe/checkout flow); if missing,
the caller receives HTTP 402.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    MarketplaceAgent,
    MarketplaceBase,
    User,
    UserPurchasedAgent,
    UserPurchasedBase,
)

logger = logging.getLogger(__name__)

ItemType = Literal["agent", "skill", "mcp_server", "base"]
_AGENT_TABLE_TYPES = {"agent", "skill", "mcp_server"}


@dataclass
class InstallResolution:
    item_type: ItemType
    item: Any  # MarketplaceAgent | MarketplaceBase
    is_base: bool

    @property
    def is_free(self) -> bool:
        return getattr(self.item, "pricing_type", "free") == "free"


async def resolve_item(db: AsyncSession, item_type: str, slug: str) -> InstallResolution:
    if item_type == "base":
        stmt = select(MarketplaceBase).where(MarketplaceBase.slug == slug, MarketplaceBase.is_active.is_(True))
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Base not found")
        return InstallResolution(item_type="base", item=row, is_base=True)

    if item_type not in _AGENT_TABLE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown item_type: {item_type}")

    stmt = select(MarketplaceAgent).where(
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.item_type == item_type,
        MarketplaceAgent.is_active.is_(True),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{item_type.replace('_', ' ').title()} not found")
    return InstallResolution(item_type=item_type, item=row, is_base=False)


async def _existing_purchase(
    db: AsyncSession, user: User, resolution: InstallResolution
) -> Any | None:
    if resolution.is_base:
        stmt = select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == user.id,
            UserPurchasedBase.base_id == resolution.item.id,
            UserPurchasedBase.is_active.is_(True),
        )
    else:
        stmt = select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == user.id,
            UserPurchasedAgent.agent_id == resolution.item.id,
            UserPurchasedAgent.is_active.is_(True),
        )
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


async def record_install(
    db: AsyncSession, user: User, resolution: InstallResolution
) -> tuple[Any, bool]:
    """Return (purchase_row, newly_created). Paid items without an active
    purchase raise 402."""
    existing = await _existing_purchase(db, user, resolution)
    if existing is not None:
        return existing, False

    if not resolution.is_free:
        raise HTTPException(
            status_code=402,
            detail="Purchase required for paid item. Complete checkout before installing.",
        )

    if resolution.is_base:
        row = UserPurchasedBase(
            user_id=user.id,
            team_id=user.default_team_id,
            base_id=resolution.item.id,
            purchase_type="free",
        )
    else:
        row = UserPurchasedAgent(
            user_id=user.id,
            team_id=user.default_team_id,
            agent_id=resolution.item.id,
            purchase_type="free",
        )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, True


def build_download_urls(resolution: InstallResolution) -> dict[str, str | None]:
    """Return the endpoint URLs the desktop client should hit to pull the body.

    These are relative to the cloud origin; callers are already tsk-authenticated
    so no extra signing is required. For bases, git clone URL is returned as-is.
    """
    slug = resolution.item.slug
    if resolution.item_type == "base":
        return {
            "git_repo_url": getattr(resolution.item, "git_repo_url", None),
            "default_branch": getattr(resolution.item, "default_branch", None),
        }
    if resolution.item_type == "skill":
        return {
            "manifest_url": f"/api/public/marketplace/skills/{slug}",
            "body_url": f"/api/public/marketplace/skills/{slug}/body",
        }
    if resolution.item_type == "mcp_server":
        return {"manifest_url": f"/api/public/marketplace/mcp-servers/{slug}"}
    return {
        "manifest_url": f"/api/public/marketplace/agents/{slug}/manifest",
        "detail_url": f"/api/public/marketplace/agents/{slug}",
    }


def purchase_to_dict(row: Any, resolution: InstallResolution | None = None) -> dict:
    """Uniform serialization of UserPurchasedAgent / UserPurchasedBase rows."""
    is_base = hasattr(row, "base_id")
    return {
        "id": str(row.id),
        "item_type": "base" if is_base else getattr(getattr(row, "agent", None), "item_type", "agent"),
        "item_id": str(row.base_id if is_base else row.agent_id),
        "purchase_type": row.purchase_type,
        "purchase_date": row.purchase_date.isoformat() if row.purchase_date else None,
        "expires_at": getattr(row, "expires_at", None).isoformat()
        if getattr(row, "expires_at", None)
        else None,
        "is_active": bool(row.is_active),
    }


__all__ = [
    "InstallResolution",
    "build_download_urls",
    "purchase_to_dict",
    "record_install",
    "resolve_item",
]
