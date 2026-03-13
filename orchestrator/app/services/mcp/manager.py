"""
Per-user MCP server manager with Redis-backed schema caching.

Handles discovery of MCP server capabilities, caching of tool/resource/prompt
schemas, and bridging into the agent's tool system.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...config import get_settings
from ...models import AgentMcpAssignment, MarketplaceAgent, UserMcpConfig
from ..cache_service import get_redis_client
from ..channels.registry import decrypt_credentials
from .bridge import bridge_mcp_prompts, bridge_mcp_resources, bridge_mcp_tools
from .client import connect_mcp

logger = logging.getLogger(__name__)

# Redis key prefix for cached MCP schemas
_CACHE_PREFIX = "mcp:schema"


class McpManager:
    """Manages MCP server discovery, caching, and tool bridging for users."""

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_server(
        self,
        server_config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Connect to an MCP server and discover all capabilities.

        Returns a dict with keys ``tools``, ``resources``, ``resource_templates``,
        and ``prompts`` -- each a JSON-serialisable list of schema dicts.
        """
        result: dict[str, Any] = {
            "tools": [],
            "resources": [],
            "resource_templates": [],
            "prompts": [],
        }

        async with connect_mcp(server_config, credentials) as session:
            # Discover tools
            try:
                tools_resp = await session.list_tools()
                tools_list = getattr(tools_resp, "tools", [])
                result["tools"] = [
                    {
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", ""),
                        "inputSchema": getattr(t, "inputSchema", None),
                    }
                    for t in tools_list
                ]
            except Exception as exc:
                logger.warning("Failed to list MCP tools: %s", exc)

            # Discover resources
            try:
                resources_resp = await session.list_resources()
                resources_list = getattr(resources_resp, "resources", [])
                result["resources"] = [
                    {
                        "uri": getattr(r, "uri", ""),
                        "name": getattr(r, "name", ""),
                        "description": getattr(r, "description", ""),
                        "mimeType": getattr(r, "mimeType", None),
                    }
                    for r in resources_list
                ]
            except Exception as exc:
                logger.warning("Failed to list MCP resources: %s", exc)

            # Discover resource templates
            try:
                templates_resp = await session.list_resource_templates()
                templates_list = getattr(templates_resp, "resource_templates", [])
                result["resource_templates"] = [
                    {
                        "uriTemplate": getattr(t, "uriTemplate", ""),
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", ""),
                    }
                    for t in templates_list
                ]
            except Exception as exc:
                logger.warning("Failed to list MCP resource templates: %s", exc)

            # Discover prompts
            try:
                prompts_resp = await session.list_prompts()
                prompts_list = getattr(prompts_resp, "prompts", [])
                result["prompts"] = [
                    {
                        "name": getattr(p, "name", ""),
                        "description": getattr(p, "description", ""),
                        "arguments": [
                            {
                                "name": getattr(a, "name", ""),
                                "description": getattr(a, "description", ""),
                                "required": getattr(a, "required", False),
                            }
                            for a in (getattr(p, "arguments", None) or [])
                        ],
                    }
                    for p in prompts_list
                ]
            except Exception as exc:
                logger.warning("Failed to list MCP prompts: %s", exc)

        return result

    # ------------------------------------------------------------------
    # User MCP context (called when building agent context)
    # ------------------------------------------------------------------

    async def get_user_mcp_context(
        self,
        user_id: str,
        db: AsyncSession,
        *,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch installed MCP servers for a user and return bridged tools + context.

        Parameters
        ----------
        user_id:
            The user whose MCP configs to load.
        db:
            Active database session.
        agent_id:
            Optional — when set, only MCP servers explicitly assigned to this
            agent via :class:`AgentMcpAssignment` are returned.  When ``None``,
            all active user MCP configs are returned (backward-compatible).

        Returns
        -------
        dict with:
            tools : list[Tool]
                Tesslate Tool objects ready for registry registration.
            mcp_configs : dict[str, dict]
                Mapping ``server_slug -> {"server": ..., "credentials": ...}``
                injected into the agent execution context so executors can reconnect.
            resource_catalog : list[dict]
                Flat list of available resources across all servers.
            prompt_catalog : list[dict]
                Flat list of available prompts across all servers.
        """
        settings = get_settings()
        cache_ttl = settings.mcp_tool_cache_ttl

        # 1. Query active UserMcpConfig rows with joined MarketplaceAgent
        if agent_id:
            # Filter to only MCP servers assigned to this specific agent
            stmt = (
                select(UserMcpConfig)
                .options(selectinload(UserMcpConfig.marketplace_agent))
                .join(
                    AgentMcpAssignment,
                    AgentMcpAssignment.mcp_config_id == UserMcpConfig.id,
                )
                .where(
                    UserMcpConfig.user_id == user_id,
                    UserMcpConfig.is_active.is_(True),
                    AgentMcpAssignment.agent_id == agent_id,
                    AgentMcpAssignment.user_id == user_id,
                    AgentMcpAssignment.enabled.is_(True),
                )
            )
        else:
            stmt = (
                select(UserMcpConfig)
                .options(selectinload(UserMcpConfig.marketplace_agent))
                .where(
                    UserMcpConfig.user_id == user_id,
                    UserMcpConfig.is_active.is_(True),
                )
            )
        result = await db.execute(stmt)
        configs: list[UserMcpConfig] = list(result.scalars().all())

        all_tools = []
        mcp_configs: dict[str, dict[str, Any]] = {}
        resource_catalog: list[dict[str, Any]] = []
        prompt_catalog: list[dict[str, Any]] = []

        for umc in configs:
            agent: MarketplaceAgent | None = umc.marketplace_agent
            if agent is None:
                logger.warning(
                    "UserMcpConfig %s has no marketplace_agent, skipping",
                    umc.id,
                )
                continue

            server_slug: str = agent.slug
            server_config: dict[str, Any] = agent.config or {}

            if not server_config.get("transport"):
                logger.debug("MCP agent '%s' has no transport configured, skipping", server_slug)
                continue

            # Decrypt user credentials
            credentials: dict[str, Any] = {}
            if umc.credentials:
                try:
                    credentials = decrypt_credentials(umc.credentials)
                except Exception as exc:
                    logger.error(
                        "Failed to decrypt credentials for MCP config %s: %s",
                        umc.id,
                        exc,
                    )
                    continue

            # 2. Check Redis cache for schemas
            agent_id_str = str(agent.id)
            cache_key = f"{_CACHE_PREFIX}:{user_id}:{agent_id_str}"
            schemas = await self._get_cached_schemas(cache_key)

            # 3. If not cached, discover and cache
            if schemas is None:
                try:
                    schemas = await self.discover_server(server_config, credentials)
                    await self._set_cached_schemas(cache_key, schemas, cache_ttl)
                except Exception as exc:
                    logger.error(
                        "MCP discovery failed for '%s' (user=%s): %s -- skipping",
                        server_slug,
                        user_id,
                        exc,
                    )
                    continue

            # Store config for executor reconnections
            mcp_configs[server_slug] = {
                "server": server_config,
                "credentials": credentials,
            }

            # 4. Bridge tools
            enabled = umc.enabled_capabilities or ["tools", "resources", "prompts"]

            if "tools" in enabled and schemas.get("tools"):
                all_tools.extend(bridge_mcp_tools(server_slug, schemas["tools"]))

            if "resources" in enabled:
                resources = schemas.get("resources", [])
                templates = schemas.get("resource_templates", [])
                resource_tool = bridge_mcp_resources(server_slug, resources, templates)
                if resource_tool:
                    all_tools.append(resource_tool)
                resource_catalog.extend(
                    {**r, "server": server_slug} for r in resources
                )

            if "prompts" in enabled and schemas.get("prompts"):
                prompt_tool = bridge_mcp_prompts(server_slug, schemas["prompts"])
                if prompt_tool:
                    all_tools.append(prompt_tool)
                prompt_catalog.extend(
                    {**p, "server": server_slug} for p in schemas["prompts"]
                )

        logger.info(
            "Built MCP context for user %s: %d servers, %d tools, %d resources, %d prompts",
            user_id,
            len(mcp_configs),
            len(all_tools),
            len(resource_catalog),
            len(prompt_catalog),
        )

        return {
            "tools": all_tools,
            "mcp_configs": mcp_configs,
            "resource_catalog": resource_catalog,
            "prompt_catalog": prompt_catalog,
        }

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    async def invalidate_cache(
        self,
        user_id: str,
        marketplace_agent_id: str,
    ) -> None:
        """Invalidate cached schemas for a specific MCP server."""
        cache_key = f"{_CACHE_PREFIX}:{user_id}:{marketplace_agent_id}"

        redis = await get_redis_client()
        if redis:
            try:
                await redis.delete(cache_key)
                logger.info("Invalidated MCP cache: %s", cache_key)
            except Exception as exc:
                logger.warning("Failed to invalidate MCP cache key %s: %s", cache_key, exc)

    # ------------------------------------------------------------------
    # Internal caching helpers
    # ------------------------------------------------------------------

    async def _get_cached_schemas(self, key: str) -> dict[str, Any] | None:
        """Read cached MCP schemas from Redis. Returns None on miss or error."""
        redis = await get_redis_client()
        if not redis:
            return None

        try:
            raw = await redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis GET failed for MCP cache key %s: %s", key, exc)

        return None

    async def _set_cached_schemas(
        self,
        key: str,
        schemas: dict[str, Any],
        ttl: int,
    ) -> None:
        """Write MCP schemas to Redis with TTL."""
        redis = await get_redis_client()
        if not redis:
            return

        try:
            await redis.setex(key, ttl, json.dumps(schemas))
            logger.debug("Cached MCP schemas: %s (TTL=%ds)", key, ttl)
        except Exception as exc:
            logger.warning("Redis SET failed for MCP cache key %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: McpManager | None = None


def get_mcp_manager() -> McpManager:
    """Return the singleton :class:`McpManager` instance."""
    global _manager
    if _manager is None:
        _manager = McpManager()
    return _manager
