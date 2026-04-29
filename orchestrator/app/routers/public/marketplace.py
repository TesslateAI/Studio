"""
Public Marketplace API — browse agents, skills, bases, MCP servers, and themes.

All endpoints use API key auth with MARKETPLACE_READ scope. Responses include
ETag / Cache-Control headers for client-side caching.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...auth_external import require_api_scope
from ...database import get_db
from ...models import (
    AgentMcpAssignment,
    AgentSkillAssignment,
    MarketplaceAgent,
    MarketplaceBase,
    Theme,
    User,
    UserMcpConfig,
    UserPurchasedAgent,
    UserPurchasedBase,
)
from ...permissions import Permission
from ._shared import add_cache_headers, apply_sort, ownership_filter, paginated_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/marketplace", tags=["public-marketplace"])

SortParam = Literal["featured", "popular", "newest", "rating"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _check_purchased(
    user: User,
    agent_or_base: Any,
    db: AsyncSession,
    *,
    is_base: bool = False,
) -> bool:
    """Return True if the user owns (or item is free) the given marketplace item."""
    if agent_or_base.pricing_type == "free":
        return True

    if is_base:
        stmt = select(UserPurchasedBase.id).where(
            ownership_filter(user, UserPurchasedBase),
            UserPurchasedBase.base_id == agent_or_base.id,
            UserPurchasedBase.is_active.is_(True),
        )
    else:
        stmt = select(UserPurchasedAgent.id).where(
            ownership_filter(user, UserPurchasedAgent),
            UserPurchasedAgent.agent_id == agent_or_base.id,
            UserPurchasedAgent.is_active.is_(True),
        )

    result = await db.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


def _agent_to_dict(agent: MarketplaceAgent, *, include_detail: bool = False) -> dict:
    """Serialize a MarketplaceAgent to a response dict."""
    creator_name = "Tesslate"
    if agent.created_by_user_id is not None:
        creator = getattr(agent, "created_by_user", None)
        if creator is not None:
            creator_name = creator.username

    data: dict[str, Any] = {
        "id": str(agent.id),
        "name": agent.name,
        "slug": agent.slug,
        "description": agent.description,
        "category": agent.category,
        "item_type": agent.item_type,
        "icon": agent.icon,
        "avatar_url": agent.avatar_url,
        "pricing_type": agent.pricing_type,
        "price": (agent.price or 0) / 100,
        "downloads": agent.downloads or 0,
        "rating": agent.rating,
        "reviews_count": agent.reviews_count or 0,
        "tags": agent.tags or [],
        "is_featured": agent.is_featured,
        "creator_type": "official" if agent.created_by_user_id is None else "community",
        "creator_name": creator_name,
    }
    if include_detail:
        data.update(
            {
                "long_description": agent.long_description,
                "system_prompt": agent.system_prompt,
                "tools": agent.tools,
                "required_models": agent.required_models,
                "features": agent.features or [],
                "preview_image": agent.preview_image,
                "source_type": agent.source_type,
                "git_repo_url": agent.git_repo_url,
                "is_forkable": agent.is_forkable,
                "model": agent.model,
                "agent_type": agent.agent_type,
            }
        )
    return data


def _base_to_dict(base: MarketplaceBase, *, include_detail: bool = False) -> dict:
    """Serialize a MarketplaceBase to a response dict."""
    data: dict[str, Any] = {
        "id": str(base.id),
        "name": base.name,
        "slug": base.slug,
        "description": base.description,
        "category": base.category,
        "icon": base.icon,
        "preview_image": base.preview_image,
        "pricing_type": base.pricing_type,
        "price": (base.price or 0) / 100,
        "downloads": base.downloads or 0,
        "rating": base.rating,
        "reviews_count": base.reviews_count or 0,
        "tags": base.tags or [],
        "tech_stack": base.tech_stack or [],
        "is_featured": base.is_featured,
        "git_repo_url": base.git_repo_url,
        "default_branch": base.default_branch,
    }
    if include_detail:
        data.update(
            {
                "long_description": base.long_description,
                "features": base.features or [],
                "source_type": base.source_type,
            }
        )
    return data


def _theme_to_dict(theme: Theme, *, include_detail: bool = False) -> dict:
    """Serialize a Theme to a response dict.

    Wave 1.5: ``Theme.id`` is now a GUID; the slug is the
    human-readable identifier external API clients (desktop sidecar,
    SDKs) key on. Expose the slug as ``id`` so clients pinned to the
    public ``/api/v1/marketplace`` surface keep working through the PK
    migration. Wave 5 ships source-aware URLs and lets us safely flip
    the public field to the GUID.
    """
    colors = (theme.theme_json or {}).get("colors", {})
    public_id = theme.slug or str(theme.id)
    data: dict[str, Any] = {
        "id": public_id,
        "name": theme.name,
        "slug": theme.slug,
        "description": theme.description,
        "category": theme.category,
        "mode": theme.mode,
        "icon": theme.icon,
        "preview_image": theme.preview_image,
        "pricing_type": theme.pricing_type,
        "price": (theme.price or 0) / 100,
        "downloads": theme.downloads or 0,
        "rating": theme.rating,
        "reviews_count": theme.reviews_count or 0,
        "tags": theme.tags or [],
        "is_featured": theme.is_featured,
        "author": theme.author,
        "version": theme.version,
        "color_swatches": {
            "primary": colors.get("primary"),
            "accent": colors.get("accent"),
            "background": colors.get("background"),
            "surface": colors.get("surface"),
        },
    }
    if include_detail:
        data.update(
            {
                "long_description": theme.long_description,
                "theme_json": theme.theme_json,
                "source_type": theme.source_type,
                "parent_theme_id": str(theme.parent_theme_id)
                if theme.parent_theme_id
                else None,
            }
        )
    return data


async def _list_marketplace_agents(
    db: AsyncSession,
    response: Response,
    type_filter,
    page: int,
    limit: int,
    category: str | None,
    pricing_type: str | None,
    search: str | None,
    sort: str,
    to_dict=_agent_to_dict,
) -> dict:
    """Shared list logic for MarketplaceAgent-backed item types."""
    filters = [
        MarketplaceAgent.is_active.is_(True),
        MarketplaceAgent.is_system.isnot(True),
        type_filter,
    ]
    if category:
        filters.append(MarketplaceAgent.category == category)
    if pricing_type:
        filters.append(MarketplaceAgent.pricing_type == pricing_type)
    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(MarketplaceAgent.name.ilike(pattern), MarketplaceAgent.description.ilike(pattern))
        )

    total = (
        await db.execute(select(func.count()).select_from(MarketplaceAgent).where(*filters))
    ).scalar_one()

    stmt = (
        select(MarketplaceAgent)
        .where(*filters)
        .options(selectinload(MarketplaceAgent.created_by_user))
    )
    stmt = apply_sort(stmt, MarketplaceAgent, sort)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    add_cache_headers(response, f"{total}:{page}:{limit}")
    return paginated_response([to_dict(a) for a in rows], total, page, limit)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace agents (excludes skills, subagents, and MCP servers)."""
    type_filter = MarketplaceAgent.item_type.notin_(["skill", "subagent", "mcp_server"])
    # Agents also require is_published
    return await _list_marketplace_agents(
        db, response, type_filter, page, limit, category, pricing_type, search, sort
    )


@router.get("/agents/{slug}")
async def get_agent(
    slug: str,
    response: Response,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get agent detail by slug."""
    stmt = select(MarketplaceAgent).where(
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.is_active.is_(True),
    )
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    add_cache_headers(response, f"{agent.id}:{agent.updated_at}")
    return _agent_to_dict(agent, include_detail=True)


@router.get("/agents/{slug}/manifest")
async def get_agent_manifest(
    slug: str,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get full agent manifest (purchase-gated). Includes skills and MCP servers."""
    stmt = select(MarketplaceAgent).where(
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.is_active.is_(True),
    )
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not await _check_purchased(user, agent, db):
        raise HTTPException(status_code=403, detail="Purchase required")

    # Load skills in one joined query instead of N+1
    skill_rows = (
        await db.execute(
            select(AgentSkillAssignment, MarketplaceAgent)
            .join(MarketplaceAgent, AgentSkillAssignment.skill_id == MarketplaceAgent.id)
            .where(
                AgentSkillAssignment.agent_id == agent.id,
                AgentSkillAssignment.enabled.is_(True),
                ownership_filter(user, AgentSkillAssignment),
            )
        )
    ).all()

    skills = [
        {
            "name": skill.name,
            "slug": skill.slug,
            "description": skill.description,
            "skill_body": skill.skill_body,
        }
        for _assignment, skill in skill_rows
    ]

    # Load MCP servers in one joined query instead of N+1
    mcp_rows = (
        await db.execute(
            select(AgentMcpAssignment, UserMcpConfig, MarketplaceAgent)
            .join(UserMcpConfig, AgentMcpAssignment.mcp_config_id == UserMcpConfig.id)
            .join(
                MarketplaceAgent,
                UserMcpConfig.marketplace_agent_id == MarketplaceAgent.id,
            )
            .where(
                AgentMcpAssignment.agent_id == agent.id,
                AgentMcpAssignment.enabled.is_(True),
                ownership_filter(user, AgentMcpAssignment),
            )
        )
    ).all()

    mcp_servers = [
        {"name": mcp_agent.name, "slug": mcp_agent.slug, "config": mcp_agent.config}
        for _assignment, _config, mcp_agent in mcp_rows
    ]

    return {
        "version": "1.0",
        "agent": {
            "name": agent.name,
            "slug": agent.slug,
            "agent_type": agent.agent_type,
            "system_prompt": agent.system_prompt,
            "model": agent.model,
            "tools": agent.tools,
            "tool_configs": agent.tool_configs,
        },
        "skills": skills,
        "mcp_servers": mcp_servers,
    }


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


@router.get("/skills")
async def list_skills(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace skills."""
    return await _list_marketplace_agents(
        db,
        response,
        MarketplaceAgent.item_type == "skill",
        page,
        limit,
        category,
        pricing_type,
        search,
        sort,
    )


@router.get("/skills/{slug}")
async def get_skill(
    slug: str,
    response: Response,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get skill detail by slug (does not include skill_body)."""
    stmt = select(MarketplaceAgent).where(
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.item_type == "skill",
        MarketplaceAgent.is_active.is_(True),
    )
    skill = (await db.execute(stmt)).scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    add_cache_headers(response, f"{skill.id}:{skill.updated_at}")
    return _agent_to_dict(skill, include_detail=True)


@router.get("/skills/{slug}/body")
async def get_skill_body(
    slug: str,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Download skill body (purchase-gated)."""
    stmt = select(MarketplaceAgent).where(
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.item_type == "skill",
        MarketplaceAgent.is_active.is_(True),
    )
    skill = (await db.execute(stmt)).scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if not await _check_purchased(user, skill, db):
        raise HTTPException(status_code=403, detail="Purchase required")

    return {"name": skill.name, "slug": skill.slug, "skill_body": skill.skill_body}


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------


@router.get("/bases")
async def list_bases(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace bases (project templates)."""
    filters = [MarketplaceBase.is_active.is_(True), MarketplaceBase.visibility == "public"]
    if category:
        filters.append(MarketplaceBase.category == category)
    if pricing_type:
        filters.append(MarketplaceBase.pricing_type == pricing_type)
    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(MarketplaceBase.name.ilike(pattern), MarketplaceBase.description.ilike(pattern))
        )

    total = (
        await db.execute(select(func.count()).select_from(MarketplaceBase).where(*filters))
    ).scalar_one()

    stmt = select(MarketplaceBase).where(*filters)
    stmt = apply_sort(stmt, MarketplaceBase, sort)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    add_cache_headers(response, f"{total}:{page}:{limit}")
    return paginated_response([_base_to_dict(b) for b in rows], total, page, limit)


@router.get("/bases/{slug}")
async def get_base(
    slug: str,
    response: Response,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get base detail by slug."""
    stmt = select(MarketplaceBase).where(
        MarketplaceBase.slug == slug,
        MarketplaceBase.is_active.is_(True),
    )
    base = (await db.execute(stmt)).scalar_one_or_none()
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    add_cache_headers(response, f"{base.id}:{base.updated_at}")
    return _base_to_dict(base, include_detail=True)


# ---------------------------------------------------------------------------
# MCP Servers
# ---------------------------------------------------------------------------


@router.get("/mcp-servers")
async def list_mcp_servers(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace MCP servers."""
    return await _list_marketplace_agents(
        db,
        response,
        MarketplaceAgent.item_type == "mcp_server",
        page,
        limit,
        category,
        pricing_type,
        search,
        sort,
    )


@router.get("/mcp-servers/{slug}")
async def get_mcp_server(
    slug: str,
    response: Response,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get MCP server detail by slug (includes config)."""
    stmt = select(MarketplaceAgent).where(
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.item_type == "mcp_server",
        MarketplaceAgent.is_active.is_(True),
    )
    server = (await db.execute(stmt)).scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    add_cache_headers(response, f"{server.id}:{server.updated_at}")
    data = _agent_to_dict(server, include_detail=True)
    data["config"] = server.config
    return data


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


@router.get("/themes")
async def list_themes(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace themes (theme_json excluded from list view)."""
    filters = [Theme.is_active.is_(True), Theme.is_published.is_(True)]
    if category:
        filters.append(Theme.category == category)
    if pricing_type:
        filters.append(Theme.pricing_type == pricing_type)
    if search:
        pattern = f"%{search}%"
        filters.append(or_(Theme.name.ilike(pattern), Theme.description.ilike(pattern)))

    total = (await db.execute(select(func.count()).select_from(Theme).where(*filters))).scalar_one()

    stmt = select(Theme).where(*filters)
    stmt = apply_sort(stmt, Theme, sort)
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    items = [_theme_to_dict(t) for t in rows]

    add_cache_headers(response, f"{total}:{page}:{limit}")
    return paginated_response(items, total, page, limit)


@router.get("/themes/{slug}")
async def get_theme(
    slug: str,
    response: Response,
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get theme detail by slug (includes full theme_json)."""
    stmt = select(Theme).where(
        Theme.slug == slug,
        Theme.is_active.is_(True),
    )
    theme = (await db.execute(stmt)).scalar_one_or_none()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    add_cache_headers(response, f"{theme.id}:{theme.updated_at}")
    return _theme_to_dict(theme, include_detail=True)
