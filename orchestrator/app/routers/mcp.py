"""
MCP marketplace install/manage CRUD endpoints.

All endpoints require JWT authentication. Handles installing MCP servers
from the marketplace, managing credentials, testing connections, and
discovering server capabilities.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import AgentMcpAssignment, MarketplaceAgent, UserMcpConfig
from ..schemas import (
    AgentMcpAssignmentResponse,
    McpConfigResponse,
    McpConfigUpdate,
    McpDiscoverResponse,
    McpInstallRequest,
    McpTestResponse,
)
from ..services.channels.registry import decrypt_credentials, encrypt_credentials
from ..services.mcp.client import connect_mcp
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["mcp"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_config_response(
    config: UserMcpConfig,
    agent: MarketplaceAgent | None = None,
) -> McpConfigResponse:
    """Build a McpConfigResponse from a UserMcpConfig row."""
    return McpConfigResponse(
        id=config.id,
        marketplace_agent_id=config.marketplace_agent_id,
        server_name=agent.name if agent else None,
        server_slug=agent.slug if agent else None,
        enabled_capabilities=config.enabled_capabilities,
        is_active=config.is_active,
        env_vars=(agent.config or {}).get("env_vars") if agent else None,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


async def _get_owned_config(
    config_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    *,
    team_id: UUID | None = None,
) -> UserMcpConfig:
    """Fetch a UserMcpConfig and verify ownership. Raises 404 if missing."""
    ownership_filter = (
        UserMcpConfig.team_id == team_id
        if team_id
        else UserMcpConfig.user_id == user_id
    )
    result = await db.execute(
        select(UserMcpConfig).where(
            UserMcpConfig.id == config_id,
            ownership_filter,
            UserMcpConfig.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="MCP configuration not found")
    return config


async def _get_agent_for_config(
    marketplace_agent_id: UUID,
    db: AsyncSession,
) -> MarketplaceAgent:
    result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == marketplace_agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Marketplace agent not found")
    return agent


async def _invalidate_mcp_cache(user_id: UUID, marketplace_agent_id: UUID) -> None:
    """Invalidate Redis cache for a user's MCP server schemas (best-effort).

    Uses the same key pattern as McpManager: ``mcp:schema:{user_id}:{agent_id}``.
    """
    try:
        from ..services.cache_service import get_redis_client

        redis = await get_redis_client()
        if redis:
            cache_key = f"mcp:schema:{user_id}:{marketplace_agent_id}"
            await redis.delete(cache_key)
            logger.debug("Invalidated MCP cache: %s", cache_key)
    except Exception:
        logger.debug("MCP cache invalidation skipped (cache unavailable)")


async def _discover_server(
    agent: MarketplaceAgent,
    credentials: dict,
) -> McpDiscoverResponse:
    """Connect to an MCP server and discover capabilities."""
    server_config = agent.config or {}
    async with connect_mcp(server_config, credentials) as session:
        tools_result = await session.list_tools()
        resources_result = await session.list_resources()
        prompts_result = await session.list_prompts()
        resource_templates_result = await session.list_resource_templates()

        tools = [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in (tools_result.tools if tools_result.tools else [])
        ]
        resources = [
            {"uri": str(r.uri), "name": r.name, "description": r.description}
            for r in (resources_result.resources if resources_result.resources else [])
        ]
        prompts = [
            {"name": p.name, "description": p.description}
            for p in (prompts_result.prompts if prompts_result.prompts else [])
        ]
        resource_templates = [
            {"uriTemplate": str(rt.uriTemplate), "name": rt.name, "description": rt.description}
            for rt in (
                resource_templates_result.resourceTemplates
                if resource_templates_result.resourceTemplates
                else []
            )
        ]

        return McpDiscoverResponse(
            tools=tools,
            resources=resources,
            prompts=prompts,
            resource_templates=resource_templates,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/install", response_model=McpConfigResponse, status_code=201)
async def install_mcp_server(
    body: McpInstallRequest,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Install an MCP server from the marketplace."""
    # Verify the marketplace item exists and is an MCP server
    agent = await _get_agent_for_config(body.marketplace_agent_id, db)
    if agent.item_type != "mcp_server":
        raise HTTPException(
            status_code=400,
            detail="Marketplace item is not an MCP server",
        )

    # Resolve active team for ownership scoping
    team_id = user.default_team_id

    # Check per-user/team server limit
    limit_filter = (
        UserMcpConfig.team_id == team_id
        if team_id
        else UserMcpConfig.user_id == user.id
    )
    count_result = await db.execute(
        select(func.count()).where(
            limit_filter,
            UserMcpConfig.is_active.is_(True),
        )
    )
    current_count = count_result.scalar() or 0
    if current_count >= settings.mcp_max_servers_per_user:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {settings.mcp_max_servers_per_user} MCP servers per user",
        )

    # Encrypt credentials if provided
    encrypted_creds = None
    if body.credentials:
        encrypted_creds = encrypt_credentials(body.credentials)

    # Determine default capabilities from server config
    server_config = agent.config or {}
    default_capabilities = server_config.get("capabilities", ["tools", "resources", "prompts"])

    config = UserMcpConfig(
        user_id=user.id,
        team_id=team_id,
        marketplace_agent_id=body.marketplace_agent_id,
        credentials=encrypted_creds,
        enabled_capabilities=default_capabilities,
        is_active=True,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    # Test connection (non-fatal)
    try:
        creds = body.credentials or {}
        await _discover_server(agent, creds)
        logger.info("MCP server %s connection verified for user %s", agent.slug, user.id)
    except Exception as e:
        logger.warning(
            "MCP server %s connection test failed (non-fatal): %s",
            agent.slug,
            str(e),
        )

    return _build_config_response(config, agent)


@router.get("/installed", response_model=list[McpConfigResponse])
async def list_installed_mcp_servers(
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active MCP server installations for the current user/team."""
    # Resolve active team for ownership scoping
    team_id = user.default_team_id
    ownership_filter = (
        UserMcpConfig.team_id == team_id
        if team_id
        else UserMcpConfig.user_id == user.id
    )

    result = await db.execute(
        select(UserMcpConfig, MarketplaceAgent)
        .join(MarketplaceAgent, UserMcpConfig.marketplace_agent_id == MarketplaceAgent.id)
        .where(
            ownership_filter,
            UserMcpConfig.is_active.is_(True),
        )
        .order_by(UserMcpConfig.created_at.desc())
    )
    rows = result.all()
    return [_build_config_response(config, agent) for config, agent in rows]


@router.get("/installed/{config_id}", response_model=McpConfigResponse)
async def get_installed_mcp_server(
    config_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single MCP server installation (credentials masked)."""
    config = await _get_owned_config(config_id, user.id, db, team_id=user.default_team_id)
    agent = await _get_agent_for_config(config.marketplace_agent_id, db)
    return _build_config_response(config, agent)


@router.patch("/installed/{config_id}", response_model=McpConfigResponse)
async def update_installed_mcp_server(
    config_id: UUID,
    body: McpConfigUpdate,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update credentials or enabled capabilities for an installed MCP server."""
    config = await _get_owned_config(config_id, user.id, db, team_id=user.default_team_id)

    if body.credentials is not None:
        config.credentials = encrypt_credentials(body.credentials)
    if body.enabled_capabilities is not None:
        config.enabled_capabilities = body.enabled_capabilities
    if body.is_active is not None:
        config.is_active = body.is_active

    await db.commit()
    await db.refresh(config)

    await _invalidate_mcp_cache(user.id, config.marketplace_agent_id)

    agent = await _get_agent_for_config(config.marketplace_agent_id, db)
    return _build_config_response(config, agent)


@router.delete("/installed/{config_id}", status_code=204)
async def uninstall_mcp_server(
    config_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an MCP server installation."""
    config = await _get_owned_config(config_id, user.id, db, team_id=user.default_team_id)
    config.is_active = False
    await db.commit()

    await _invalidate_mcp_cache(user.id, config.marketplace_agent_id)


@router.post("/installed/{config_id}/test", response_model=McpTestResponse)
async def test_mcp_server(
    config_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Test connection to an installed MCP server and return capability counts."""
    config = await _get_owned_config(config_id, user.id, db, team_id=user.default_team_id)
    agent = await _get_agent_for_config(config.marketplace_agent_id, db)

    credentials = {}
    if config.credentials:
        try:
            credentials = decrypt_credentials(config.credentials)
        except Exception:
            return McpTestResponse(
                success=False,
                error="Failed to decrypt stored credentials",
            )

    try:
        discovery = await _discover_server(agent, credentials)
        return McpTestResponse(
            success=True,
            tool_count=len(discovery.tools),
            resource_count=len(discovery.resources),
            prompt_count=len(discovery.prompts),
        )
    except Exception as e:
        logger.warning("MCP test failed for config %s: %s", config_id, str(e))
        return McpTestResponse(
            success=False,
            error=str(e),
        )


@router.post("/installed/{config_id}/discover", response_model=McpDiscoverResponse)
async def discover_mcp_server(
    config_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Full re-discovery of an MCP server's capabilities (invalidates cache)."""
    config = await _get_owned_config(config_id, user.id, db, team_id=user.default_team_id)
    agent = await _get_agent_for_config(config.marketplace_agent_id, db)

    await _invalidate_mcp_cache(user.id, config.marketplace_agent_id)

    credentials = {}
    if config.credentials:
        try:
            credentials = decrypt_credentials(config.credentials)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Failed to decrypt stored credentials",
            ) from None

    try:
        return await _discover_server(agent, credentials)
    except Exception as e:
        logger.error("MCP discover failed for config %s: %s", config_id, str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to MCP server: {e}",
        ) from e


# ---------------------------------------------------------------------------
# Agent-level MCP server assignment
# ---------------------------------------------------------------------------


@router.post("/installed/{config_id}/assign/{agent_id}", response_model=AgentMcpAssignmentResponse)
async def assign_mcp_to_agent(
    config_id: UUID,
    agent_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an installed MCP server to a specific agent."""
    # Resolve active team for ownership scoping
    team_id = user.default_team_id

    # Verify ownership of the MCP config
    config = await _get_owned_config(config_id, user.id, db, team_id=team_id)

    # Verify the agent exists and is active
    agent_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == agent_id,
            MarketplaceAgent.is_active.is_(True),
        )
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check for existing assignment
    assignment_ownership = (
        AgentMcpAssignment.team_id == team_id
        if team_id
        else AgentMcpAssignment.user_id == user.id
    )
    existing_result = await db.execute(
        select(AgentMcpAssignment).where(
            AgentMcpAssignment.agent_id == agent_id,
            AgentMcpAssignment.mcp_config_id == config_id,
            assignment_ownership,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        if existing.enabled:
            # Already assigned and enabled – return as-is
            marketplace_agent = await _get_agent_for_config(config.marketplace_agent_id, db)
            return AgentMcpAssignmentResponse(
                id=existing.id,
                agent_id=existing.agent_id,
                mcp_config_id=existing.mcp_config_id,
                server_name=marketplace_agent.name,
                server_slug=marketplace_agent.slug,
                enabled=existing.enabled,
                added_at=existing.added_at,
            )
        # Re-enable previously disabled assignment
        existing.enabled = True
        await db.commit()
        await db.refresh(existing)
        marketplace_agent = await _get_agent_for_config(config.marketplace_agent_id, db)
        return AgentMcpAssignmentResponse(
            id=existing.id,
            agent_id=existing.agent_id,
            mcp_config_id=existing.mcp_config_id,
            server_name=marketplace_agent.name,
            server_slug=marketplace_agent.slug,
            enabled=existing.enabled,
            added_at=existing.added_at,
        )

    assignment = AgentMcpAssignment(
        agent_id=agent_id,
        mcp_config_id=config_id,
        user_id=user.id,
        team_id=team_id,
        enabled=True,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    marketplace_agent = await _get_agent_for_config(config.marketplace_agent_id, db)
    return AgentMcpAssignmentResponse(
        id=assignment.id,
        agent_id=assignment.agent_id,
        mcp_config_id=assignment.mcp_config_id,
        server_name=marketplace_agent.name,
        server_slug=marketplace_agent.slug,
        enabled=assignment.enabled,
        added_at=assignment.added_at,
    )


@router.delete("/installed/{config_id}/assign/{agent_id}", status_code=204)
async def unassign_mcp_from_agent(
    config_id: UUID,
    agent_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an MCP server from a specific agent."""
    # Resolve active team for ownership scoping
    team_id = user.default_team_id
    ownership_filter = (
        AgentMcpAssignment.team_id == team_id
        if team_id
        else AgentMcpAssignment.user_id == user.id
    )

    result = await db.execute(
        select(AgentMcpAssignment).where(
            AgentMcpAssignment.agent_id == agent_id,
            AgentMcpAssignment.mcp_config_id == config_id,
            ownership_filter,
        )
    )
    assignment = result.scalar_one_or_none()

    if not assignment:
        raise HTTPException(status_code=404, detail="MCP assignment not found")

    await db.delete(assignment)
    await db.commit()


@router.get("/agent/{agent_id}/servers", response_model=list[AgentMcpAssignmentResponse])
async def get_agent_mcp_servers(
    agent_id: UUID,
    user=Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List MCP servers assigned to a specific agent."""
    # Resolve active team for ownership scoping
    team_id = user.default_team_id
    ownership_filter = (
        AgentMcpAssignment.team_id == team_id
        if team_id
        else AgentMcpAssignment.user_id == user.id
    )

    # Verify agent exists
    agent_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == agent_id,
            MarketplaceAgent.is_active.is_(True),
        )
    )
    if not agent_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    result = await db.execute(
        select(AgentMcpAssignment, UserMcpConfig, MarketplaceAgent)
        .join(UserMcpConfig, AgentMcpAssignment.mcp_config_id == UserMcpConfig.id)
        .join(MarketplaceAgent, UserMcpConfig.marketplace_agent_id == MarketplaceAgent.id)
        .where(
            AgentMcpAssignment.agent_id == agent_id,
            ownership_filter,
            AgentMcpAssignment.enabled.is_(True),
            UserMcpConfig.is_active.is_(True),
        )
    )
    rows = result.all()

    return [
        AgentMcpAssignmentResponse(
            id=assignment.id,
            agent_id=assignment.agent_id,
            mcp_config_id=assignment.mcp_config_id,
            server_name=marketplace_agent.name,
            server_slug=marketplace_agent.slug,
            enabled=assignment.enabled,
            added_at=assignment.added_at,
        )
        for assignment, _config, marketplace_agent in rows
    ]
