"""
Marketplace install / receipt endpoints.

Complements `/api/public/marketplace/*` (browse/manifest/body) with the write
surface the desktop client needs: record an install, list owned items, and
acknowledge local installation completion so the client can flip its source
indicator from "cloud" to "local".

Paid-item gates are enforced server-side via
`services.public.marketplace_install_service.record_install` — free items are
auto-recorded; paid items without an existing purchase return 402.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...database import get_db
from ...models import (
    MarketplaceAgent,
    MarketplaceBase,
    MarketplaceSource,
    User,
    UserPurchasedAgent,
    UserPurchasedBase,
)
from ...permissions import Permission, get_team_membership
from ...services.marketplace_federation import install_guard, mcp_install_prompt
from ...services.public.marketplace_install_service import (
    build_download_urls,
    purchase_to_dict,
    record_install,
    resolve_item,
)
from ._deps import audit_write, scoped
from ._shared import add_cache_headers, paginated_response

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = Permission.MARKETPLACE_INSTALL

router = APIRouter(prefix="/api/v1/marketplace", tags=["public-marketplace-install"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InstallRequest(BaseModel):
    item_type: Literal["agent", "skill", "mcp_server", "base"]
    slug: str = Field(..., min_length=1, max_length=200)
    # Wave 4 install_guard confirmation flow. ``private`` sources require an
    # explicit per-install confirmation for ``mcp_server`` (and apps) — the
    # client first POSTs without ``confirmed`` and gets back a 409 with the
    # scope/tool list, then re-submits with ``confirmed=true``.
    confirmed: bool = False


class InstallResponse(BaseModel):
    receipt_id: UUID
    item_type: str
    slug: str
    newly_installed: bool
    purchase_type: str
    download: dict


class AckRequest(BaseModel):
    installed_path: str | None = Field(default=None, max_length=500)
    app_version: str | None = Field(default=None, max_length=40)


# ---------------------------------------------------------------------------
# POST /install
# ---------------------------------------------------------------------------


@router.post("/install", response_model=InstallResponse)
async def install_item(
    body: InstallRequest,
    user: User = Depends(scoped(Permission.MARKETPLACE_INSTALL)),
    db: AsyncSession = Depends(get_db),
) -> InstallResponse:
    resolution = await resolve_item(db, body.item_type, body.slug)

    # Wave 4: trust-level enforcement. Untrusted sources can be blocked outright
    # (mcp_server / app), private sources require per-install confirmation for
    # those same kinds, and team-scoped local sources require the requester to
    # be an active member of the owning team. This MUST run before
    # ``record_install`` mutates state (purchase rows, etc).
    source = await _load_install_source(db, resolution.item.source_id)
    _enforce_install_guard(
        source=source,
        item_type=body.item_type,
        resolution=resolution,
        user=user,
        confirmed=body.confirmed,
    )
    if source is not None and source.scope == "team" and source.team_id is not None:
        membership = await get_team_membership(db, source.team_id, user.id)
        if membership is None:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "install_blocked",
                    "reason": "local_team_owner_check_required",
                    "source_handle": source.handle,
                    "kind": body.item_type,
                },
            )

    purchase, created = await record_install(db, user, resolution)

    await audit_write(
        db=db,
        user=user,
        action="marketplace.install",
        resource_type=body.item_type,
        resource_id=resolution.item.id,
        details={"slug": body.slug, "newly_installed": created},
    )

    return InstallResponse(
        receipt_id=purchase.id,
        item_type=body.item_type,
        slug=body.slug,
        newly_installed=created,
        purchase_type=purchase.purchase_type,
        download=build_download_urls(resolution),
    )


# ---------------------------------------------------------------------------
# Install-gate helpers
# ---------------------------------------------------------------------------


async def _load_install_source(
    db: AsyncSession, source_id: UUID | None
) -> MarketplaceSource | None:
    """Look up the ``MarketplaceSource`` for a resolved item.

    Returns ``None`` for legacy rows that were never backfilled to a source.
    The install gate treats ``None`` as the local-system sentinel — these
    are pre-federation user-authored rows and were always installable by
    their creator.
    """
    if source_id is None:
        return None
    result = await db.execute(
        select(MarketplaceSource).where(MarketplaceSource.id == source_id)
    )
    return result.scalar_one_or_none()


def _enforce_install_guard(
    *,
    source: MarketplaceSource | None,
    item_type: str,
    resolution,
    user: User,
    confirmed: bool,
) -> None:
    """Run ``install_guard`` against ``source`` and translate deny outcomes
    into the same HTTP shape the authenticated browser-side install paths
    use (``orchestrator/app/routers/marketplace.py::_ensure_install_allowed``).

    For ``mcp_server`` confirmation responses we additionally include the
    ``prompt`` block (transport / command / url / args / env_keys /
    scope_list) parsed from the manifest so the desktop UI can render the
    permission modal without a second round-trip.
    """
    if source is None:
        # Pre-Wave-1 backfill safety: legacy rows treated as local-system,
        # which install_guard would also allow.
        return

    # ``mcp_server`` decisions need the manifest so install_guard can extract
    # tool/scope data. Other kinds don't carry per-install scope surfaces.
    version_meta: dict | None = None
    if item_type == "mcp_server":
        agent_config = (
            resolution.item.config if isinstance(resolution.item.config, dict) else {}
        )
        version_meta = {"manifest": agent_config}

    decision = install_guard(
        source,
        item_type,
        version_meta=version_meta,
        requester_user_id=user.id,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "install_blocked",
                "reason": decision.reason,
                "source_handle": source.handle,
                "kind": item_type,
            },
        )
    if decision.requires_confirmation and not confirmed:
        detail: dict = {
            "error": "install_requires_confirmation",
            "reason": decision.reason,
            "source_handle": source.handle,
            "kind": item_type,
            "scope_tool_list": decision.scope_tool_list or [],
            "destructive_tools": decision.destructive_tools,
        }
        if item_type == "mcp_server":
            agent_config = (
                resolution.item.config if isinstance(resolution.item.config, dict) else {}
            )
            prompt = mcp_install_prompt(agent_config)
            detail["prompt"] = {
                "transport": prompt.transport,
                "command": prompt.command,
                "url": prompt.url,
                "args": prompt.args,
                "env_keys": prompt.env_keys,
                "scope_list": prompt.scope_list,
            }
        raise HTTPException(status_code=409, detail=detail)


# ---------------------------------------------------------------------------
# GET /installed
# ---------------------------------------------------------------------------


@router.get("/installed")
async def list_installed(
    response: Response,
    item_type: Literal["agent", "skill", "mcp_server", "base"] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    source: str | None = Query(
        default=None,
        description=(
            "Filter installed items by the marketplace source they were "
            "synced from. Joined via MarketplaceAgent.source_id / "
            "MarketplaceBase.source_id."
        ),
    ),
    user: User = Depends(scoped(Permission.MARKETPLACE_INSTALL)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    include_agents = item_type in (None, "agent", "skill", "mcp_server")
    include_bases = item_type in (None, "base")

    # Wave 4: optional source filter on the installed list. We resolve the
    # handle once and apply the filter as a JOIN+WHERE in each branch so
    # the ID comparison happens server-side.
    source_id_filter = None
    if source:
        source_row = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.handle == source)
            )
        ).scalar_one_or_none()
        if source_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown marketplace source handle: {source!r}",
            )
        source_id_filter = source_row.id

    rows: list = []

    if include_agents:
        agent_stmt = (
            select(UserPurchasedAgent)
            .options(selectinload(UserPurchasedAgent.agent))
            .where(
                UserPurchasedAgent.user_id == user.id,
                UserPurchasedAgent.is_active.is_(True),
            )
        )
        if source_id_filter is not None:
            agent_stmt = agent_stmt.join(
                MarketplaceAgent, MarketplaceAgent.id == UserPurchasedAgent.agent_id
            ).where(MarketplaceAgent.source_id == source_id_filter)
        agent_rows = (await db.execute(agent_stmt)).scalars().all()
        if item_type and item_type != "base":
            agent_rows = [r for r in agent_rows if r.agent and r.agent.item_type == item_type]
        rows.extend(agent_rows)

    if include_bases:
        base_stmt = select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == user.id,
            UserPurchasedBase.is_active.is_(True),
        )
        if source_id_filter is not None:
            base_stmt = base_stmt.join(
                MarketplaceBase, MarketplaceBase.id == UserPurchasedBase.base_id
            ).where(MarketplaceBase.source_id == source_id_filter)
        base_rows = (await db.execute(base_stmt)).scalars().all()
        rows.extend(base_rows)

    rows.sort(key=lambda r: r.purchase_date or 0, reverse=True)
    total = len(rows)
    start = (page - 1) * limit
    page_rows = rows[start : start + limit]
    items = [purchase_to_dict(r) for r in page_rows]

    add_cache_headers(response, etag_source=f"installed:{user.id}:{total}:{page}", max_age=15)
    return paginated_response(items, total, page, limit)


# ---------------------------------------------------------------------------
# POST /install/{id}/ack
# ---------------------------------------------------------------------------


@router.post("/install/{receipt_id}/ack")
async def ack_install(
    receipt_id: UUID,
    body: AckRequest,
    user: User = Depends(scoped(Permission.MARKETPLACE_INSTALL)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Receipt can be either UserPurchasedAgent or UserPurchasedBase. Try both.
    agent_row = (
        await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.id == receipt_id,
                UserPurchasedAgent.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    base_row = None
    if agent_row is None:
        base_row = (
            await db.execute(
                select(UserPurchasedBase).where(
                    UserPurchasedBase.id == receipt_id,
                    UserPurchasedBase.user_id == user.id,
                )
            )
        ).scalar_one_or_none()

    if agent_row is None and base_row is None:
        raise HTTPException(status_code=404, detail="Receipt not found")

    resource_type = "agent" if agent_row is not None else "base"

    await audit_write(
        db=db,
        user=user,
        action="marketplace.install.ack",
        resource_type=resource_type,
        resource_id=receipt_id,
        details={
            "installed_path": body.installed_path,
            "app_version": body.app_version,
        },
    )

    return {
        "receipt_id": str(receipt_id),
        "acknowledged": True,
        "resource_type": resource_type,
    }
