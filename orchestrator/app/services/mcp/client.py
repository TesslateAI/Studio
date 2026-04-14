"""
MCP client — multi-transport support (stdio, streamable-http, SSE).

Provides ``connect_mcp()``, an async context manager that yields an
initialised :class:`ClientSession` for any supported transport.

TRANSPORT SUPPORT
-----------------
- **stdio**: Spawns a child process (e.g. ``npx``), communicates over
  stdin/stdout.  Environment variables are filtered to prevent credential
  leakage — only safe baseline vars plus explicit config/credentials are
  passed.  Sessions live for the duration of the caller's ``async with``
  block (typically one agent task).

- **streamable-http**: Stateless HTTP calls to remote MCP server
  providers.  Ideal for cloud-hosted MCP servers.

- **sse**: Legacy Server-Sent Events transport for older MCP servers.
  Being superseded by streamable-http but still used by some servers.

Session Lifecycle
-----------------
This module provides *transport-level* connections only.  For task-scoped
session pooling with reconnection and tool refresh, see ``session_pool.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from ...config import get_settings
from .security import build_safe_env, sanitize_error

logger = logging.getLogger(__name__)

# Optional SSE import (may not be available in all mcp SDK versions)
try:
    from mcp.client.sse import sse_client

    _SSE_AVAILABLE = True
except ImportError:
    _SSE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def connect_mcp(
    server_config: dict[str, Any],
    credentials: dict[str, Any],
    *,
    sampling_callback: Any | None = None,
    message_handler: Any | None = None,
    user_mcp_config_id: Any | None = None,
    db: Any | None = None,
):
    """Connect to an MCP server via any supported transport.

    Yields a fully initialised :class:`ClientSession`.

    Parameters
    ----------
    server_config:
        Server configuration from ``MarketplaceAgent.config`` JSON.
        Required keys depend on transport:
          - stdio: ``command``, ``args`` (optional), ``env`` (optional)
          - streamable-http: ``url``, ``auth_type``
          - sse: ``url``, ``auth_type``
    credentials:
        Decrypted credential dict from ``UserMcpConfig.credentials``.
    sampling_callback:
        Optional callback for MCP sampling/createMessage requests.
    message_handler:
        Optional handler for server notifications (tool list changes, etc.).
    user_mcp_config_id:
        UUID of the ``UserMcpConfig`` row — required when
        ``server_config["auth_type"] == "oauth"`` so we can locate the
        ``McpOAuthConnection`` in Postgres.
    db:
        Active :class:`sqlalchemy.ext.asyncio.AsyncSession` — required when
        ``server_config["auth_type"] == "oauth"``.
    """
    transport = server_config.get("transport", "streamable-http")
    settings = get_settings()

    session_kwargs: dict[str, Any] = {}
    if sampling_callback is not None:
        session_kwargs["sampling_callback"] = sampling_callback
    if message_handler is not None:
        session_kwargs["message_handler"] = message_handler

    match transport:
        case "stdio":
            async with _connect_stdio(
                server_config, credentials, settings, session_kwargs
            ) as session:
                yield session
        case "streamable-http":
            async with _connect_streamable_http(
                server_config,
                credentials,
                settings,
                session_kwargs,
                user_mcp_config_id=user_mcp_config_id,
                db=db,
            ) as session:
                yield session
        case "sse":
            async with _connect_sse(
                server_config, credentials, settings, session_kwargs
            ) as session:
                yield session
        case _:
            raise ValueError(
                f"Unsupported MCP transport: {transport!r}. "
                "Supported transports: stdio, streamable-http, sse."
            )


# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------


def _resolve_command(command: str, env: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Resolve a bare command to an absolute path.

    Searches the filtered PATH from ``env``.  If found, prepends the
    command's directory to PATH so child processes can also find it.
    Falls back to common locations if not on PATH.
    """
    # Already absolute?
    if os.path.isabs(command) and os.path.isfile(command):
        return command, env

    # Search filtered PATH
    resolved = shutil.which(command, path=env.get("PATH"))
    if resolved:
        cmd_dir = os.path.dirname(resolved)
        current_path = env.get("PATH", "")
        if cmd_dir not in current_path.split(os.pathsep):
            env["PATH"] = f"{cmd_dir}{os.pathsep}{current_path}" if current_path else cmd_dir
        return resolved, env

    # Fallback candidates
    candidates = [
        os.path.expanduser(f"~/.local/bin/{command}"),
        f"/usr/local/bin/{command}",
        f"/usr/bin/{command}",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            cmd_dir = os.path.dirname(candidate)
            current_path = env.get("PATH", "")
            env["PATH"] = f"{cmd_dir}{os.pathsep}{current_path}" if current_path else cmd_dir
            return candidate, env

    # Let it fail at subprocess level with a clear error
    return command, env


@asynccontextmanager
async def _connect_stdio(
    config: dict[str, Any],
    credentials: dict[str, Any],
    settings: Any,
    session_kwargs: dict[str, Any],
):
    """Establish a stdio MCP connection (subprocess)."""
    command = config.get("command")
    if not command:
        raise ValueError(
            "Stdio MCP server config missing 'command'. "
            'Expected e.g. {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}'
        )

    args: list[str] = config.get("args", [])
    user_env: dict[str, str] | None = config.get("env")

    # Build filtered environment (security: no credential leakage)
    if settings.mcp_stdio_env_filter:
        safe_env = build_safe_env(user_env, credentials)
    else:
        # Disabled filtering — inherit everything (not recommended for production)
        safe_env = {**os.environ}
        if user_env:
            safe_env.update(user_env)
        if credentials:
            safe_env.update(credentials)

    # Resolve command to absolute path
    command, safe_env = _resolve_command(command, safe_env)

    server_params = StdioServerParameters(
        command=command,
        args=args,
        env=safe_env,
    )

    logger.info(
        "Connecting to MCP server via stdio: %s %s",
        command,
        " ".join(args[:3]) + ("..." if len(args) > 3 else ""),
    )

    try:
        async with (
            stdio_client(server_params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream, **session_kwargs) as session,
        ):
            await asyncio.wait_for(
                session.initialize(),
                timeout=settings.mcp_stdio_connect_timeout,
            )
            logger.info("MCP stdio session initialised: %s", command)
            yield session
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            sanitize_error(
                f"MCP stdio command not found: {command!r}. "
                f"Ensure it is installed and available on PATH. "
                f"Original error: {exc}"
            )
        ) from exc


# ---------------------------------------------------------------------------
# Streamable HTTP transport
# ---------------------------------------------------------------------------


def _build_auth_headers(
    config: dict[str, Any],
    credentials: dict[str, Any],
) -> dict[str, str]:
    """Build HTTP headers from config auth_type + credentials."""
    headers: dict[str, str] = {}
    auth_type = config.get("auth_type", "none")

    if auth_type == "bearer":
        token = (
            credentials.get("token")
            or credentials.get("api_key")
            or credentials.get("API_KEY")
            or credentials.get("TOKEN")
        )
        if token:
            headers["Authorization"] = f"Bearer {token}"

    # Merge any explicit headers from config
    config_headers = config.get("headers")
    if config_headers and isinstance(config_headers, dict):
        headers.update(config_headers)

    return headers


@asynccontextmanager
async def _connect_streamable_http(
    config: dict[str, Any],
    credentials: dict[str, Any],
    settings: Any,
    session_kwargs: dict[str, Any],
    *,
    user_mcp_config_id: Any | None = None,
    db: Any | None = None,
):
    """Establish a Streamable HTTP MCP connection.

    When ``config["auth_type"] == "oauth"``, wires the MCP SDK's
    :class:`OAuthClientProvider` onto the underlying ``httpx.AsyncClient`` so
    refresh-on-401 persists new tokens via :class:`PostgresTokenStorage`.
    Missing or un-refreshable tokens raise :class:`ReauthRequired`.
    """
    url: str = config["url"]
    timeout = settings.mcp_tool_timeout
    auth_type = config.get("auth_type", "none")

    logger.info("Connecting to MCP server via streamable-http: %s (auth=%s)", url, auth_type)

    import httpx

    auth = None
    if auth_type == "oauth":
        if user_mcp_config_id is None or db is None:
            raise ValueError(
                "OAuth MCP connection requires user_mcp_config_id and db; "
                "pass them through connect_mcp(...)"
            )

        from uuid import UUID as _UUID

        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata

        from .oauth_flow import ReauthRequired
        from .oauth_storage import PostgresTokenStorage

        # Coerce potential str → UUID; SQLAlchemy + asyncpg are strict about types.
        config_uuid = user_mcp_config_id if isinstance(
            user_mcp_config_id, _UUID
        ) else _UUID(str(user_mcp_config_id))

        oauth_storage = PostgresTokenStorage(db, config_uuid)
        tokens = await oauth_storage.get_tokens()
        if tokens is None:
            raise ReauthRequired(
                server_url=url,
                config_id=config_uuid,
                message="No stored OAuth tokens — reconnect required",
            )

        # Mirror the stored client's token-endpoint auth method so refresh
        # doesn't silently downgrade to Basic when the client was registered
        # with client_secret_post or `none`.
        stored_client = await oauth_storage.get_client_info()
        token_auth_method = (
            stored_client.token_endpoint_auth_method if stored_client else "client_secret_basic"
        )
        stored_redirects = (
            list(stored_client.redirect_uris) if stored_client and stored_client.redirect_uris
            else ["https://unused.local/mcp-runtime"]
        )

        # Runtime redirect / callback handlers: if we ever get here at runtime
        # the user needs to re-auth interactively via Settings → Connectors.
        async def _raise_reauth_redirect(_: str) -> None:
            raise ReauthRequired(server_url=url, config_id=config_uuid)

        async def _raise_reauth_callback() -> tuple[str, str | None]:
            raise ReauthRequired(server_url=url, config_id=config_uuid)

        client_metadata = OAuthClientMetadata(
            redirect_uris=stored_redirects,
            token_endpoint_auth_method=token_auth_method,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name="Tesslate Studio (runtime)",
        )
        auth = OAuthClientProvider(
            server_url=url,
            client_metadata=client_metadata,
            storage=oauth_storage,
            redirect_handler=_raise_reauth_redirect,
            callback_handler=_raise_reauth_callback,
        )
        headers: dict[str, str] = {}
    else:
        headers = _build_auth_headers(config, credentials)

    http_client = httpx.AsyncClient(
        headers=headers or None,
        timeout=timeout,
        auth=auth,
    )

    try:
        async with (
            streamable_http_client(url=url, http_client=http_client) as (
                read_stream,
                write_stream,
                _,
            ),
            ClientSession(read_stream, write_stream, **session_kwargs) as session,
        ):
            await session.initialize()
            logger.info("MCP streamable-http session initialised for %s", url)
            yield session
    except BaseExceptionGroup as eg:
        # The mcp SDK's streamable-http transport can raise ExceptionGroup
        # during cleanup.  Suppress if all sub-exceptions are cancellations.
        non_cancelled = eg.subgroup(lambda e: not isinstance(e, asyncio.CancelledError))
        if non_cancelled:
            raise non_cancelled from eg
        logger.debug("Suppressed benign TaskGroup cleanup errors for %s", url)
    finally:
        await http_client.aclose()


# ---------------------------------------------------------------------------
# SSE transport (legacy)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _connect_sse(
    config: dict[str, Any],
    credentials: dict[str, Any],
    settings: Any,
    session_kwargs: dict[str, Any],
):
    """Establish an SSE MCP connection (legacy transport)."""
    if not _SSE_AVAILABLE:
        raise ImportError(
            "SSE transport requires the 'sse' extra of the mcp package. "
            "Install with: pip install 'mcp[sse]'"
        )

    url: str = config["url"]
    timeout = settings.mcp_tool_timeout
    headers = _build_auth_headers(config, credentials)

    logger.info("Connecting to MCP server via SSE: %s", url)

    sse_kwargs: dict[str, Any] = {"url": url}
    if headers:
        sse_kwargs["headers"] = headers
    if timeout:
        sse_kwargs["timeout"] = timeout

    async with (
        sse_client(**sse_kwargs) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, **session_kwargs) as session,
    ):
        await session.initialize()
        logger.info("MCP SSE session initialised for %s", url)
        yield session
