"""
Bridges MCP tools, resources, and prompts into Tesslate's agent ToolRegistry.

Each MCP capability is wrapped in a :class:`Tool` dataclass that the agent can
invoke like any built-in tool.  Executors connect to the MCP server per call
(stateless) — the subprocess or HTTP connection lives only for the duration of
a single tool invocation, then is torn down.

All error messages are sanitised before reaching the LLM to prevent credential
leakage.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from ...agent.tools.output_formatter import error_output, success_output
from ...agent.tools.registry import Tool, ToolCategory
from ...database import AsyncSessionLocal
from .client import connect_mcp
from .oauth_flow import ReauthRequired
from .security import sanitize_error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool bridge
# ---------------------------------------------------------------------------


def bridge_mcp_tools(server_slug: str, mcp_tools: list[dict[str, Any]]) -> list[Tool]:
    """Convert a list of MCP tool schemas into Tesslate :class:`Tool` objects.

    Parameters
    ----------
    server_slug:
        URL-safe identifier for the MCP server (used as tool-name prefix).
    mcp_tools:
        Tool descriptions returned by ``session.list_tools()``, serialised
        to dicts (each has ``name``, ``description``, ``inputSchema``).

    Returns
    -------
    list[Tool]
        One Tesslate Tool per MCP tool, ready for registration.
    """
    tools: list[Tool] = []

    for mcp_tool in mcp_tools:
        tool_name = mcp_tool.get("name", "unknown")
        description = mcp_tool.get("description", "MCP tool (no description)")
        input_schema = mcp_tool.get("inputSchema") or {
            "type": "object",
            "properties": {},
        }

        tesslate_name = f"mcp__{server_slug}__{tool_name}"
        executor = _make_tool_executor(server_slug, tool_name)

        tools.append(
            Tool(
                name=tesslate_name,
                description=f"[MCP:{server_slug}] {description}",
                parameters=input_schema,
                executor=executor,
                category=ToolCategory.WEB,
                # Remote MCP server owns the tool's state (sessions,
                # cursors, server-side auth) — not locally checkpointable.
                state_serializable=False,
                # Each call opens a fresh MCP session (stdio subprocess
                # or streamable-http) outside the agent loop.
                holds_external_state=True,
            )
        )

    return tools


# ---------------------------------------------------------------------------
# Resource bridge
# ---------------------------------------------------------------------------


def bridge_mcp_resources(
    server_slug: str,
    mcp_resources: list[dict[str, Any]],
    mcp_templates: list[dict[str, Any]],
) -> Tool | None:
    """Create a single meta-tool that reads any resource exposed by the server.

    Returns ``None`` when the server has no resources or templates.
    """
    if not mcp_resources and not mcp_templates:
        return None

    lines = [f"[MCP:{server_slug}] Read a resource by URI."]

    if mcp_resources:
        lines.append("\nAvailable resources:")
        for res in mcp_resources:
            uri = res.get("uri", "?")
            name = res.get("name", uri)
            lines.append(f"  - {name}: {uri}")

    if mcp_templates:
        lines.append("\nURI templates:")
        for tpl in mcp_templates:
            uri_template = tpl.get("uriTemplate", "?")
            name = tpl.get("name", uri_template)
            lines.append(f"  - {name}: {uri_template}")

    return Tool(
        name=f"mcp__{server_slug}__read_resource",
        description="\n".join(lines),
        parameters={
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": "Resource URI to read",
                },
            },
            "required": ["uri"],
        },
        executor=_make_resource_executor(server_slug),
        category=ToolCategory.WEB,
        # Remote server owns resource state; each call opens a fresh
        # MCP session outside the agent loop.
        state_serializable=False,
        holds_external_state=True,
    )


# ---------------------------------------------------------------------------
# Prompt bridge
# ---------------------------------------------------------------------------


def bridge_mcp_prompts(
    server_slug: str,
    mcp_prompts: list[dict[str, Any]],
) -> Tool | None:
    """Create a single meta-tool that fetches any prompt exposed by the server.

    Returns ``None`` when the server has no prompts.
    """
    if not mcp_prompts:
        return None

    lines = [f"[MCP:{server_slug}] Fetch a prompt by name."]
    lines.append("\nAvailable prompts:")
    for prompt in mcp_prompts:
        name = prompt.get("name", "?")
        desc = prompt.get("description", "")
        args_list = prompt.get("arguments", [])
        arg_names = ", ".join(a.get("name", "?") for a in args_list) if args_list else "none"
        lines.append(f"  - {name} (args: {arg_names}): {desc}")

    return Tool(
        name=f"mcp__{server_slug}__get_prompt",
        description="\n".join(lines),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Prompt name to fetch",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass to the prompt",
                    "default": {},
                },
            },
            "required": ["name"],
        },
        executor=_make_prompt_executor(server_slug),
        category=ToolCategory.WEB,
        # Remote server owns prompt state; each call opens a fresh
        # MCP session outside the agent loop.
        state_serializable=False,
        holds_external_state=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_tool_result_text(result: Any) -> str:
    """Extract text from an MCP tool call result.

    Prefers structured output (MCP spec 2025-06-18+), falls back to
    content block text extraction.
    """
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        import json as _json

        return _json.dumps(structured, indent=2, default=str)

    texts: list[str] = []
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text is not None:
            texts.append(text)
    return "\n".join(texts) if texts else "(no output)"


def _get_mcp_config(
    server_slug: str,
    context: dict[str, Any],
) -> dict[str, Any] | None:
    """Look up MCP server config from execution context.

    Returns ``None`` (with no exception) if the server is not configured,
    allowing the caller to return a clean ``error_output``.
    """
    mcp_configs: dict[str, Any] | None = context.get("mcp_configs")
    if not mcp_configs:
        return None
    return mcp_configs.get(server_slug)


@asynccontextmanager
async def _open_mcp_session(cfg: dict[str, Any]):
    """Open a session for an MCP config, handling OAuth DB plumbing.

    For OAuth connectors we open a fresh :class:`AsyncSession` scoped to this
    tool invocation so the SDK's refresh-on-401 path can persist new tokens.
    For static-auth connectors we pass ``db=None`` and the client's non-OAuth
    branch runs exactly as before.
    """
    server = cfg["server"]
    credentials = cfg.get("credentials") or {}
    user_mcp_config_id = cfg.get("user_mcp_config_id")
    auth_type = (server or {}).get("auth_type")

    if auth_type == "oauth":
        async with AsyncSessionLocal() as db:
            try:
                async with connect_mcp(
                    server,
                    credentials,
                    user_mcp_config_id=user_mcp_config_id,
                    db=db,
                ) as session:
                    yield session
                # Persist refreshed tokens (written through PostgresTokenStorage).
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    else:
        async with connect_mcp(server, credentials) as session:
            yield session


def _reauth_output(exc: ReauthRequired, server_slug: str) -> dict[str, Any]:
    """Return a structured tool result signalling re-auth is required.

    The frontend's ``AgentStep`` detects ``_mcp_reauth_required`` and renders a
    ReauthBanner linking back to Settings → Connectors.
    """
    return {
        "success": False,
        "error": exc.message,
        "_mcp_reauth_required": True,
        "server_slug": server_slug,
        "server_url": exc.server_url,
        "config_id": str(exc.config_id) if exc.config_id else None,
        "message": exc.message,
        "status": "reauth_required",
    }


def _forward_structured(result: Any) -> dict[str, Any]:
    """Forward ``_mcp_structured`` (incl. citation) and ``meta`` from the SDK result.

    Safe-noop when neither is present. The frontend chat renderer detects
    ``_mcp_structured.citation`` and renders a CitationCard.
    """
    extras: dict[str, Any] = {}
    structured = getattr(result, "structuredContent", None)
    if structured:
        extras["_mcp_structured"] = structured
    meta = getattr(result, "meta", None)
    if meta:
        extras["_mcp_meta"] = meta
    return extras


# ---------------------------------------------------------------------------
# Executor factories (closures)
# ---------------------------------------------------------------------------


def _make_tool_executor(server_slug: str, mcp_tool_name: str):
    """Return an async executor that calls a single MCP tool.

    Each invocation opens a fresh connection (stdio subprocess or HTTP
    request), calls the tool, and tears down the connection.
    """

    async def _executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        cfg = _get_mcp_config(server_slug, context)
        if cfg is None:
            return error_output(
                f"MCP server '{server_slug}' is not configured for this session.",
                suggestion="Install the MCP server from the marketplace and assign it to this agent.",
            )

        try:
            async with _open_mcp_session(cfg) as session:
                result = await session.call_tool(mcp_tool_name, params)

            output_text = _extract_tool_result_text(result)
            structured = _forward_structured(result)

            if getattr(result, "isError", False):
                return {
                    **error_output(
                        f"MCP tool '{mcp_tool_name}' returned an error: {sanitize_error(output_text)}",
                    ),
                    **structured,
                }

            # Flatten: the raw MCP payload is the primary content. Weak
            # models (Kimi K2, small OSS, etc.) skip nested `details.output`
            # and confabulate from priors. Surfacing the payload as both the
            # top-level `result` field AND inlined in the `message` forces
            # it into the model's attention when rendering the tool_result
            # block.
            return {
                **success_output(
                    f"MCP tool '{mcp_tool_name}' result:\n{output_text}",
                    result=output_text,
                ),
                **structured,
            }

        except ReauthRequired as exc:
            return _reauth_output(exc, server_slug)
        except Exception as exc:
            logger.error(
                "MCP tool call failed: server=%s tool=%s error=%s",
                server_slug,
                mcp_tool_name,
                sanitize_error(str(exc)),
                exc_info=True,
            )
            return error_output(
                sanitize_error(f"Failed to call MCP tool '{mcp_tool_name}': {exc}"),
                suggestion="Check that the MCP server is reachable and credentials are valid.",
            )

    return _executor


def _make_resource_executor(server_slug: str):
    """Return an async executor that reads an MCP resource."""

    async def _executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri", "")
        if not uri:
            return error_output("Missing required parameter 'uri'.")

        cfg = _get_mcp_config(server_slug, context)
        if cfg is None:
            return error_output(
                f"MCP server '{server_slug}' is not configured for this session.",
            )

        try:
            async with _open_mcp_session(cfg) as session:
                result = await session.read_resource(uri)

            texts: list[str] = []
            for item in getattr(result, "contents", []):
                text = getattr(item, "text", None)
                if text is not None:
                    texts.append(text)
            output_text = "\n".join(texts) if texts else "(empty resource)"

            return success_output(
                f"Read resource: {uri}",
                details={"content": output_text},
            )

        except ReauthRequired as exc:
            return _reauth_output(exc, server_slug)
        except Exception as exc:
            logger.error(
                "MCP resource read failed: server=%s uri=%s error=%s",
                server_slug,
                uri,
                sanitize_error(str(exc)),
                exc_info=True,
            )
            return error_output(
                sanitize_error(f"Failed to read MCP resource '{uri}': {exc}"),
                suggestion="Verify the resource URI is correct and the server is reachable.",
            )

    return _executor


def _make_prompt_executor(server_slug: str):
    """Return an async executor that fetches an MCP prompt."""

    async def _executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        if not name:
            return error_output("Missing required parameter 'name'.")

        cfg = _get_mcp_config(server_slug, context)
        if cfg is None:
            return error_output(
                f"MCP server '{server_slug}' is not configured for this session.",
            )

        try:
            async with _open_mcp_session(cfg) as session:
                result = await session.get_prompt(name, arguments)

            texts: list[str] = []
            for msg in getattr(result, "messages", []):
                content = getattr(msg, "content", None)
                if content:
                    text = getattr(content, "text", None)
                    if text is not None:
                        texts.append(text)
            output_text = "\n".join(texts) if texts else "(empty prompt)"

            return success_output(
                f"Fetched prompt: {name}",
                details={"content": output_text},
            )

        except ReauthRequired as exc:
            return _reauth_output(exc, server_slug)
        except Exception as exc:
            logger.error(
                "MCP prompt fetch failed: server=%s prompt=%s error=%s",
                server_slug,
                name,
                sanitize_error(str(exc)),
                exc_info=True,
            )
            return error_output(
                sanitize_error(f"Failed to fetch MCP prompt '{name}': {exc}"),
                suggestion="Verify the prompt name and arguments are correct.",
            )

    return _executor
