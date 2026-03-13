"""
MCP client with dual transport support (stdio + Streamable HTTP).

Uses the official ``mcp`` Python SDK (>=1.8.0) to connect to MCP servers,
negotiate capabilities, and yield an initialised ClientSession.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client

from ...config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def connect_mcp(
    server_config: dict[str, Any],
    credentials: dict[str, Any],
):
    """Connect to an MCP server using the appropriate transport.

    Yields a fully initialised :class:`ClientSession`.

    Parameters
    ----------
    server_config:
        Server configuration from ``MarketplaceAgent.config`` JSON.
        Required keys depend on the transport:

        * ``transport`` – ``"stdio"`` or ``"streamable-http"``
        * **stdio**: ``command``, ``args`` (list[str]), ``env_vars`` (list[str])
        * **streamable-http**: ``url``, ``auth_type`` (``"bearer"`` | ``"none"``)

    credentials:
        Decrypted credential dict from ``UserMcpConfig.credentials``.
        Contains actual values referenced by ``env_vars``
        (e.g. ``{"GITHUB_TOKEN": "ghp_..."}``).
    """
    transport = server_config.get("transport", "stdio")
    settings = get_settings()
    timeout = settings.mcp_tool_timeout

    if transport == "stdio":
        async with _connect_stdio(server_config, credentials, timeout) as session:
            yield session
        return

    if transport == "streamable-http":
        async with _connect_streamable_http(server_config, credentials, timeout) as session:
            yield session
        return

    raise ValueError(f"Unsupported MCP transport: {transport!r}")


# -- internal helpers --------------------------------------------------------


@asynccontextmanager
async def _connect_stdio(
    config: dict[str, Any],
    credentials: dict[str, Any],
    timeout: int,
):
    """Establish an stdio MCP connection."""
    command: str = config["command"]
    args: list[str] = config.get("args", [])
    env_var_names: list[str] = config.get("env_vars", [])

    # Build environment: inherit current env, overlay credential values for
    # the env-var names the server declares it needs.
    env = dict(os.environ)
    for var_name in env_var_names:
        value = credentials.get(var_name)
        if value is not None:
            env[var_name] = str(value)

    params = StdioServerParameters(command=command, args=args, env=env)

    logger.info("Connecting to MCP server via stdio: %s %s", command, " ".join(args))

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            logger.info("MCP stdio session initialised for %s", command)
            yield session


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

    async with sse_client(url=url, headers=headers, timeout=timeout) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            logger.info("MCP streamable-http session initialised for %s", url)
            yield session
