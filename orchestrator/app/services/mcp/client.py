"""
MCP client — streamable-http transport only.

Uses the official ``mcp`` Python SDK (>=1.9.2) to connect to remote MCP
servers over HTTP and yield an initialised ClientSession.

TRANSPORT POLICY
----------------
Tesslate only supports **streamable-http** MCP transport. Stdio transport is
explicitly rejected because it spawns a child process (typically ``npx``) per
tool call, per user, on orchestrator pods — which doesn't scale for
multi-tenant SaaS. With 1000 concurrent users, that would mean 1000+ Node.js
processes eating CPU/memory on our infra. Streamable-http makes stateless HTTP
calls to remote MCP server providers, with per-user rate limits via their own
API keys.

See ``docs/orchestrator/services/mcp.md`` for the full rationale.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ...config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def connect_mcp(
    server_config: dict[str, Any],
    credentials: dict[str, Any],
):
    """Connect to an MCP server via streamable-http transport.

    Yields a fully initialised :class:`ClientSession`.

    Parameters
    ----------
    server_config:
        Server configuration from ``MarketplaceAgent.config`` JSON.
        Required keys: ``transport`` (must be ``"streamable-http"``),
        ``url``, ``auth_type`` (``"bearer"`` | ``"none"``).

    credentials:
        Decrypted credential dict from ``UserMcpConfig.credentials``.
        Contains actual values (e.g. ``{"token": "sk-..."}``).
    """
    transport = server_config.get("transport", "streamable-http")

    if transport == "stdio":
        raise ValueError(
            "Stdio MCP transport is not supported. Tesslate requires streamable-http "
            "transport for multi-tenant scalability. Stdio spawns a process per tool "
            "call per user on orchestrator pods, which doesn't scale. "
            "See docs/orchestrator/services/mcp.md"
        )

    if transport != "streamable-http":
        raise ValueError(
            f"Unsupported MCP transport: {transport!r}. "
            "Only 'streamable-http' is supported. See docs/orchestrator/services/mcp.md"
        )

    settings = get_settings()
    timeout = settings.mcp_tool_timeout

    async with _connect_streamable_http(server_config, credentials, timeout) as session:
        yield session


# -- internal helpers --------------------------------------------------------


@asynccontextmanager
async def _connect_streamable_http(
    config: dict[str, Any],
    credentials: dict[str, Any],
    timeout: int,
):
    """Establish a Streamable HTTP MCP connection."""
    url: str = config["url"]
    auth_type: str = config.get("auth_type", "none")

    headers: dict[str, str] = {}
    if auth_type == "bearer":
        # Expect a single token value; try common credential key names.
        token = (
            credentials.get("token")
            or credentials.get("api_key")
            or credentials.get("API_KEY")
            or credentials.get("TOKEN")
        )
        if token:
            headers["Authorization"] = f"Bearer {token}"

    logger.info("Connecting to MCP server via streamable-http: %s", url)

    import httpx

    http_client = httpx.AsyncClient(headers=headers or None, timeout=timeout)

    try:
        async with streamable_http_client(url=url, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                logger.info("MCP streamable-http session initialised for %s", url)
                yield session
    except BaseExceptionGroup as eg:
        # The mcp SDK's streamable-http transport can raise ExceptionGroup
        # during cleanup (e.g. cancelled background listeners). These are
        # benign — the session already yielded and completed successfully.
        # We only suppress if all sub-exceptions are cancellations.
        non_cancelled = eg.subgroup(lambda e: not isinstance(e, asyncio.CancelledError))
        if non_cancelled:
            raise non_cancelled
        logger.debug("Suppressed benign TaskGroup cleanup errors for %s", url)
    finally:
        await http_client.aclose()
