"""
Per-user MCP server manager with Redis-backed schema caching.

Handles discovery of MCP server capabilities, caching of tool/resource/prompt
schemas, and bridging into the agent's tool system.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import MarketplaceAgent, UserMcpConfig
from ..cache_service import get_redis_client
from ..channels.registry import decrypt_credentials
from .bridge import bridge_mcp_prompts, bridge_mcp_resources, bridge_mcp_tools
from .client import connect_mcp
from .scoping import resolve_mcp_configs

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
        *,
        user_mcp_config_id: Any | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Connect to an MCP server and discover all capabilities.

        Returns a dict with keys ``tools``, ``resources``, ``resource_templates``,
        and ``prompts`` -- each a JSON-serialisable list of schema dicts.

        ``user_mcp_config_id`` + ``db`` are forwarded to :func:`connect_mcp` so
        OAuth-backed connectors can locate their :class:`McpOAuthConnection`.
        """
        result: dict[str, Any] = {
            "tools": [],
            "resources": [],
            "resource_templates": [],
            "prompts": [],
        }

        async with connect_mcp(
            server_config,
            credentials,
            user_mcp_config_id=user_mcp_config_id,
            db=db,
        ) as session:
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
                        "uri": str(getattr(r, "uri", "")),
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
                templates_list = getattr(templates_resp, "resourceTemplates", [])
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
        team_id: UUID | str | None = None,
        project_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Fetch installed MCP servers for a user and return bridged tools + context.

        Scope resolution uses :func:`services.mcp.scoping.resolve_mcp_configs`
        to implement ``project > user > team`` precedence across the user's
        active teams, the request's team, and the current project.

        Parameters
        ----------
        user_id:
            The user whose MCP configs to load.
        db:
            Active database session.
        agent_id:
            Optional — when set, only MCP servers explicitly assigned to this
            agent via :class:`AgentMcpAssignment` are loaded.  When ``None``,
            all in-scope user MCP configs are returned directly.
        team_id:
            Active team for this execution — team-scoped rows for this team
            participate even when the user isn't a member (rare, admin path).
        project_id:
            Active project — project-scoped overrides take precedence.

        Returns
        -------
        dict with:
            tools : list[Tool]
                Tesslate Tool objects ready for registry registration.
            mcp_configs : dict[str, dict]
                Mapping ``server_slug -> {"server", "credentials", "user_mcp_config_id"}``
                injected into the agent execution context so executors can reconnect.
            resource_catalog : list[dict]
                Flat list of available resources across all servers.
            prompt_catalog : list[dict]
                Flat list of available prompts across all servers.
        """
        settings = get_settings()
        cache_ttl = settings.mcp_tool_cache_ttl

        user_uuid = _coerce_uuid(user_id)
        team_uuid = _coerce_uuid(team_id) if team_id else None
        project_uuid = _coerce_uuid(project_id) if project_id else None
        agent_uuid = _coerce_uuid(agent_id) if agent_id else None

        logger.debug(
            "MCP context resolve: user=%s team=%s project=%s agent=%s",
            user_uuid,
            team_uuid,
            project_uuid,
            agent_uuid,
        )

        configs: list[UserMcpConfig] = await resolve_mcp_configs(
            db,
            user_id=user_uuid,
            team_id=team_uuid,
            project_id=project_uuid,
            agent_id=agent_uuid,
        )

        all_tools = []
        mcp_configs: dict[str, dict[str, Any]] = {}
        resource_catalog: list[dict[str, Any]] = []
        prompt_catalog: list[dict[str, Any]] = []
        unavailable_servers: list[dict[str, Any]] = []

        for umc in configs:
            agent: MarketplaceAgent | None = umc.marketplace_agent
            # Catalog rows require a joined MarketplaceAgent; custom connectors
            # (marketplace_agent_id IS NULL) derive server info from the row
            # directly.
            if agent is not None:
                # Normalize hyphens to underscores: some model providers
                # silently rewrite '-' → '_' in function names, which then
                # fails the registry lookup ('mcp__mcp-linear__x' registered
                # but agent emits 'mcp__mcp_linear__x').
                server_slug = agent.slug.replace("-", "_")
                server_config = dict(agent.config or {})
            else:
                # Custom connector: synthesize a slug + config from the row.
                # Server URL lives on the paired McpOAuthConnection and is
                # loaded lazily below if needed.
                server_slug = f"custom_{str(umc.id)[:8]}"
                server_config = {
                    "transport": "streamable-http",
                    "auth_type": "oauth",
                    "url": None,  # populated below from oauth_connection
                }

            # For OAuth custom connectors, hydrate the server URL from the
            # paired row so the manager+client can actually connect.
            if server_config.get("auth_type") == "oauth" and not server_config.get("url"):
                oauth_row = getattr(umc, "oauth_connection", None)
                if oauth_row is not None and getattr(oauth_row, "server_url", None):
                    server_config["url"] = oauth_row.server_url

            if not server_config.get("transport"):
                logger.debug("MCP config %s has no transport configured, skipping", umc.id)
                continue

            # Decrypt user credentials (legacy static auth). OAuth connectors
            # don't use this — tokens live in mcp_oauth_connections.
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

            # 2. Check Redis cache for schemas (keyed on config id — per-scope,
            #    per-install — so disabled_tools toggles invalidate cleanly).
            cache_key = f"{_CACHE_PREFIX}:{user_id}:{umc.id}"
            schemas = await self._get_cached_schemas(cache_key)

            # 3. If not cached, discover and cache
            if schemas is None:
                try:
                    schemas = await self.discover_server(
                        server_config,
                        credentials,
                        user_mcp_config_id=umc.id,
                        db=db,
                    )
                    await self._set_cached_schemas(cache_key, schemas, cache_ttl)
                    # Discovery succeeded → clear any stale reauth flag.
                    # Use flush (not commit) to avoid side-effects on the
                    # worker's shared session — the worker commits at the
                    # end of the task lifecycle.
                    if umc.needs_reauth or umc.last_auth_error:
                        umc.needs_reauth = False
                        umc.last_auth_error = None
                        with contextlib.suppress(Exception):
                            await db.flush()
                except Exception as exc:
                    msg = str(exc)
                    is_auth = _is_auth_error(exc, msg)
                    logger.error(
                        "MCP discovery failed for '%s' (user=%s): %s -- skipping%s",
                        server_slug,
                        user_id,
                        msg,
                        " (marking needs_reauth)" if is_auth else "",
                    )
                    if is_auth:
                        umc.needs_reauth = True
                        umc.last_auth_error = msg[:500]
                        with contextlib.suppress(Exception):
                            await db.flush()
                    unavailable_servers.append(
                        {
                            "server_slug": server_slug,
                            "reason": "auth_failed" if is_auth else "discovery_failed",
                            "error": msg[:200],
                        }
                    )
                    continue

            # Apply the user's per-tool disabled_tools filter before bridging.
            disabled_tools = set(umc.disabled_tools or [])
            filtered_tools = [
                t
                for t in (schemas.get("tools") or [])
                if _prefixed_tool_name(server_slug, t) not in disabled_tools
            ]

            # Store config for executor reconnections (bridge → connect_mcp).
            mcp_configs[server_slug] = {
                "server": server_config,
                "credentials": credentials,
                "user_mcp_config_id": str(umc.id),
            }

            # 4. Bridge tools
            enabled = umc.enabled_capabilities or ["tools", "resources", "prompts"]

            if "tools" in enabled and filtered_tools:
                all_tools.extend(bridge_mcp_tools(server_slug, filtered_tools))

            if "resources" in enabled:
                resources = schemas.get("resources", [])
                templates = schemas.get("resource_templates", [])
                resource_tool = bridge_mcp_resources(server_slug, resources, templates)
                if resource_tool:
                    all_tools.append(resource_tool)
                resource_catalog.extend({**r, "server": server_slug} for r in resources)

            if "prompts" in enabled and schemas.get("prompts"):
                prompt_tool = bridge_mcp_prompts(server_slug, schemas["prompts"])
                if prompt_tool:
                    all_tools.append(prompt_tool)
                prompt_catalog.extend({**p, "server": server_slug} for p in schemas["prompts"])

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
            "unavailable_servers": unavailable_servers,
        }

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    async def invalidate_cache(
        self,
        user_id: str,
        user_mcp_config_id: str,
    ) -> None:
        """Invalidate cached schemas for a specific user/config pair.

        Cache keys are now ``mcp:schema:{user_id}:{user_mcp_config_id}`` — the
        config id (not the marketplace agent id) so per-scope installs don't
        collide and ``disabled_tools`` toggles invalidate cleanly.
        """
        cache_key = f"{_CACHE_PREFIX}:{user_id}:{user_mcp_config_id}"

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_uuid(val: Any) -> UUID:
    """Return a UUID regardless of whether the caller passed a str or UUID."""
    if isinstance(val, UUID):
        return val
    return UUID(str(val))


def _prefixed_tool_name(server_slug: str, tool: dict[str, Any]) -> str:
    """Build the Tesslate-prefixed tool name for disabled_tools matching."""
    return f"mcp__{server_slug}__{tool.get('name', '')}"


_AUTH_ERROR_MARKERS = (
    "401",
    "unauthorized",
    "invalid_token",
    "invalid_grant",
    "token expired",
    "expired token",
)

# 403/forbidden is intentionally excluded — it usually means "authenticated
# but insufficient permissions" (authZ, not authN). Re-auth won't fix a
# permissions problem and creates a confusing loop for the user.


def _is_auth_error(exc: Exception, msg: str) -> bool:
    """Best-effort detector for auth-failure exceptions raised during discovery.

    MCP SDK errors wrap OAuth 401s inside TaskGroup exceptions whose message
    contains the transport error, so we match on substrings rather than type.

    Only matches authentication failures (expired/invalid tokens, 401), not
    authorization failures (403/forbidden) which indicate scope issues rather
    than stale credentials.
    """
    lowered = msg.lower()
    if any(m in lowered for m in _AUTH_ERROR_MARKERS):
        return True
    # ReauthRequired is the explicit typed case.
    try:
        from .oauth_flow import ReauthRequired

        if isinstance(exc, ReauthRequired):
            return True
    except ImportError:
        pass
    return False
