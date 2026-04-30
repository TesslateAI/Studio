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
    MarketplaceSource,
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

# Wave 4: public API surfaces tesslate-official by default (the externally
# documented source), but accepts ``?source=<handle>`` for federation-aware
# clients (desktop, SDK consumers that have explicitly subscribed to a
# community/private source). Untrusted sources are not surfaced via the
# public API even when explicitly requested — the orchestrator's
# authenticated UI is the only surface that lets users browse those.
_PUBLIC_DEFAULT_SOURCE_HANDLE = "tesslate-official"
_PUBLIC_ALLOWED_TRUST_LEVELS: frozenset[str] = frozenset(
    {"official", "admin_trusted"}
)


async def _resolve_public_source_filter(
    db: AsyncSession, source_handle: str | None
) -> tuple[Any, MarketplaceSource | None]:
    """Resolve ``?source=<handle>`` for the public API surface.

    Returns ``(source_id_filter, source_row)``:
      - ``source_id_filter`` is a UUID when an explicit handle was provided
        and the resulting source has trust >= admin_trusted. ``None`` when
        the caller omitted ``source`` (we still default to tesslate-official
        for safety — see below).
      - ``source_row`` is the resolved row when a handle was provided so
        the caller can attach handle/trust to the response payload.

    Public endpoints intentionally do NOT support cross-source mode (no
    "All sources" — that's authenticated UI behaviour). When ``source`` is
    omitted, the filter defaults to ``tesslate-official``.

    Raises 404 for unknown handles, 403 when the requested source is
    private or untrusted (those aren't surfaced via the public API).
    """
    handle = source_handle or _PUBLIC_DEFAULT_SOURCE_HANDLE
    src = (
        await db.execute(
            select(MarketplaceSource).where(MarketplaceSource.handle == handle)
        )
    ).scalar_one_or_none()
    if src is None:
        if source_handle is None:
            # No tesslate-official seeded yet (test envs, fresh installs);
            # fall through with no source filter — the existing behavior.
            return (None, None)
        raise HTTPException(
            status_code=404,
            detail=f"Unknown marketplace source handle: {handle!r}",
        )
    if src.trust_level not in _PUBLIC_ALLOWED_TRUST_LEVELS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Source {handle!r} is not exposed via the public API "
                f"(trust_level={src.trust_level!r}). Use the authenticated "
                "UI to browse private or untrusted sources."
            ),
        )
    return (src.id, src)


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


def _agent_to_dict(
    agent: MarketplaceAgent,
    *,
    include_detail: bool = False,
    source: MarketplaceSource | None = None,
) -> dict:
    """Serialize a MarketplaceAgent to a response dict.

    Wave 4: ``source`` is the joined ``MarketplaceSource`` row used to
    populate ``creator_name`` (the source's ``display_name``) when the
    item has no explicit user creator. Replaces the legacy ``"Tesslate"``
    hardcode that the pre-federation public API used.
    """
    creator_name: str | None = None
    if agent.created_by_user_id is not None:
        creator = getattr(agent, "created_by_user", None)
        if creator is not None:
            creator_name = creator.username
        creator_type = "community"
    else:
        if source is not None:
            display_name_val = str(source.display_name) if source.display_name is not None else ""
            if display_name_val:
                creator_name = display_name_val
        creator_type = "official" if (
            source is None or str(source.trust_level) == "official"
        ) else "community"
    if not creator_name:
        # Hard fallback: the source registry hadn't been seeded yet at
        # call time. We still want a non-empty name in the response.
        creator_name = str(source.handle) if source is not None else "Community"

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
        "creator_type": creator_type,
        "creator_name": creator_name,
        "source_handle": source.handle if source is not None else None,
        "source_trust_level": source.trust_level if source is not None else None,
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
    *,
    source_id: Any | None = None,
    source_row: MarketplaceSource | None = None,
    to_dict=_agent_to_dict,
) -> dict:
    """Shared list logic for MarketplaceAgent-backed item types."""
    filters = [
        MarketplaceAgent.is_active.is_(True),
        MarketplaceAgent.is_system.isnot(True),
        MarketplaceAgent.deleted_upstream.is_(False),
        type_filter,
    ]
    if source_id is not None:
        filters.append(MarketplaceAgent.source_id == source_id)
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
    return paginated_response(
        [to_dict(a, source=source_row) for a in rows], total, page, limit
    )


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
    source: str | None = Query(
        default=None,
        description=(
            "Marketplace source handle. Defaults to tesslate-official. "
            "Private/untrusted sources are not exposed via the public API."
        ),
    ),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace agents (excludes skills, subagents, and MCP servers)."""
    source_id, source_row = await _resolve_public_source_filter(db, source)
    type_filter = MarketplaceAgent.item_type.notin_(["skill", "subagent", "mcp_server"])
    # Agents also require is_published
    return await _list_marketplace_agents(
        db,
        response,
        type_filter,
        page,
        limit,
        category,
        pricing_type,
        search,
        sort,
        source_id=source_id,
        source_row=source_row,
    )


@router.get("/agents/{slug}")
async def get_agent(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get agent detail by slug."""
    source_id, source_row = await _resolve_public_source_filter(db, source)
    filters = [
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.is_active.is_(True),
    ]
    if source_id is not None:
        filters.append(MarketplaceAgent.source_id == source_id)
    stmt = select(MarketplaceAgent).where(*filters)
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if source_row is None and agent.source_id is not None:
        source_row = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.id == agent.source_id)
            )
        ).scalar_one_or_none()

    add_cache_headers(response, f"{agent.id}:{agent.updated_at}")
    return _agent_to_dict(agent, include_detail=True, source=source_row)


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
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace skills."""
    source_id, source_row = await _resolve_public_source_filter(db, source)
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
        source_id=source_id,
        source_row=source_row,
    )


@router.get("/skills/{slug}")
async def get_skill(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get skill detail by slug (does not include skill_body)."""
    source_id, source_row = await _resolve_public_source_filter(db, source)
    filters = [
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.item_type == "skill",
        MarketplaceAgent.is_active.is_(True),
    ]
    if source_id is not None:
        filters.append(MarketplaceAgent.source_id == source_id)
    stmt = select(MarketplaceAgent).where(*filters)
    skill = (await db.execute(stmt)).scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if source_row is None and skill.source_id is not None:
        source_row = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.id == skill.source_id)
            )
        ).scalar_one_or_none()

    add_cache_headers(response, f"{skill.id}:{skill.updated_at}")
    return _agent_to_dict(skill, include_detail=True, source=source_row)


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
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace bases (project templates)."""
    source_id, _source_row = await _resolve_public_source_filter(db, source)
    filters = [
        MarketplaceBase.is_active.is_(True),
        MarketplaceBase.deleted_upstream.is_(False),
        MarketplaceBase.visibility == "public",
    ]
    if source_id is not None:
        filters.append(MarketplaceBase.source_id == source_id)
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
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get base detail by slug."""
    source_id, _source_row = await _resolve_public_source_filter(db, source)
    filters = [
        MarketplaceBase.slug == slug,
        MarketplaceBase.is_active.is_(True),
    ]
    if source_id is not None:
        filters.append(MarketplaceBase.source_id == source_id)
    stmt = select(MarketplaceBase).where(*filters)
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
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace MCP servers."""
    source_id, source_row = await _resolve_public_source_filter(db, source)
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
        source_id=source_id,
        source_row=source_row,
    )


@router.get("/mcp-servers/{slug}")
async def get_mcp_server(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get MCP server detail by slug (includes config)."""
    source_id, source_row = await _resolve_public_source_filter(db, source)
    filters = [
        MarketplaceAgent.slug == slug,
        MarketplaceAgent.item_type == "mcp_server",
        MarketplaceAgent.is_active.is_(True),
    ]
    if source_id is not None:
        filters.append(MarketplaceAgent.source_id == source_id)
    stmt = select(MarketplaceAgent).where(*filters)
    server = (await db.execute(stmt)).scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if source_row is None and server.source_id is not None:
        source_row = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.id == server.source_id)
            )
        ).scalar_one_or_none()

    add_cache_headers(response, f"{server.id}:{server.updated_at}")
    data = _agent_to_dict(server, include_detail=True, source=source_row)
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
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace themes (theme_json excluded from list view)."""
    source_id, _source_row = await _resolve_public_source_filter(db, source)
    filters = [
        Theme.is_active.is_(True),
        Theme.deleted_upstream.is_(False),
        Theme.is_published.is_(True),
    ]
    if source_id is not None:
        filters.append(Theme.source_id == source_id)
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
    source: str | None = Query(default=None),
    user: User = Depends(require_api_scope(Permission.MARKETPLACE_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Get theme detail by slug (includes full theme_json)."""
    source_id, _source_row = await _resolve_public_source_filter(db, source)
    filters = [
        Theme.slug == slug,
        Theme.is_active.is_(True),
    ]
    if source_id is not None:
        filters.append(Theme.source_id == source_id)
    stmt = select(Theme).where(*filters)
    theme = (await db.execute(stmt)).scalar_one_or_none()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    add_cache_headers(response, f"{theme.id}:{theme.updated_at}")
    return _theme_to_dict(theme, include_detail=True)
