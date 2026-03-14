"""
Bridges MCP tools, resources, and prompts into Tesslate's agent ToolRegistry.

Each MCP capability is wrapped in a :class:`Tool` dataclass that the agent can
invoke like any built-in tool.  All executors reconnect to the MCP server on
every call (stateless) so we never hold long-lived subprocess handles.
"""

from __future__ import annotations

import logging
from typing import Any

from ...agent.tools.output_formatter import error_output, success_output
from ...agent.tools.registry import Tool, ToolCategory
from .client import connect_mcp

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

        # Build a closure that captures the original MCP tool name.
        executor = _make_tool_executor(server_slug, tool_name)

        tools.append(
            Tool(
                name=tesslate_name,
                description=f"[MCP:{server_slug}] {description}",
                parameters=input_schema,
                executor=executor,
                category=ToolCategory.WEB,
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

    # Build description listing available URIs / templates.
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

    description = "\n".join(lines)

    executor = _make_resource_executor(server_slug)

    return Tool(
        name=f"mcp__{server_slug}__read_resource",
        description=description,
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
        executor=executor,
        category=ToolCategory.WEB,
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

    description = "\n".join(lines)

    executor = _make_prompt_executor(server_slug)

    return Tool(
        name=f"mcp__{server_slug}__get_prompt",
        description=description,
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
        executor=executor,
        category=ToolCategory.WEB,
    )


# ---------------------------------------------------------------------------
# Executor factories (closures)
# ---------------------------------------------------------------------------


def _make_tool_executor(server_slug: str, mcp_tool_name: str):
    """Return an async executor that calls a single MCP tool."""

    async def _executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        mcp_configs: dict[str, Any] | None = context.get("mcp_configs")
        if not mcp_configs or server_slug not in mcp_configs:
            return error_output(
                f"MCP server '{server_slug}' is not configured for this session.",
                suggestion="Ensure the MCP server is installed and active in your settings.",
            )

        cfg = mcp_configs[server_slug]

        try:
            async with connect_mcp(cfg["server"], cfg["credentials"]) as session:
                result = await session.call_tool(mcp_tool_name, params)

            # Prefer structured output if available (MCP spec 2025-06-18+)
            structured = getattr(result, "structuredContent", None)
            if structured is not None:
                import json as _json

                output_text = _json.dumps(structured, indent=2, default=str)
            else:
                # Extract text from content items.
                texts: list[str] = []
                for item in getattr(result, "content", []):
                    text = getattr(item, "text", None)
                    if text is not None:
                        texts.append(text)
                output_text = "\n".join(texts) if texts else "(no output)"

            if getattr(result, "isError", False):
                return error_output(
                    f"MCP tool '{mcp_tool_name}' returned an error.",
                    details={"output": output_text},
                )

            return success_output(
                f"MCP tool '{mcp_tool_name}' completed.",
                details={"output": output_text},
            )

        except Exception as exc:
            logger.error(
                "MCP tool call failed: server=%s tool=%s error=%s",
                server_slug,
                mcp_tool_name,
                exc,
                exc_info=True,
            )
            return error_output(
                f"Failed to call MCP tool '{mcp_tool_name}': {exc}",
                suggestion="Check that the MCP server is reachable and credentials are valid.",
            )

    return _executor


def _make_resource_executor(server_slug: str):
    """Return an async executor that reads an MCP resource."""

    async def _executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        mcp_configs = context.get("mcp_configs")
        if not mcp_configs or server_slug not in mcp_configs:
            return error_output(
                f"MCP server '{server_slug}' is not configured for this session.",
            )

        uri = params.get("uri", "")
        if not uri:
            return error_output("Missing required parameter 'uri'.")

        cfg = mcp_configs[server_slug]

        try:
            async with connect_mcp(cfg["server"], cfg["credentials"]) as session:
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

        except Exception as exc:
            logger.error(
                "MCP resource read failed: server=%s uri=%s error=%s",
                server_slug,
                uri,
                exc,
                exc_info=True,
            )
            return error_output(
                f"Failed to read MCP resource '{uri}': {exc}",
                suggestion="Verify the resource URI is correct and the server is reachable.",
            )

    return _executor


def _make_prompt_executor(server_slug: str):
    """Return an async executor that fetches an MCP prompt."""

    async def _executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        mcp_configs = context.get("mcp_configs")
        if not mcp_configs or server_slug not in mcp_configs:
            return error_output(
                f"MCP server '{server_slug}' is not configured for this session.",
            )

        name = params.get("name", "")
        arguments = params.get("arguments", {})
        if not name:
            return error_output("Missing required parameter 'name'.")

        cfg = mcp_configs[server_slug]

        try:
            async with connect_mcp(cfg["server"], cfg["credentials"]) as session:
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

        except Exception as exc:
            logger.error(
                "MCP prompt fetch failed: server=%s prompt=%s error=%s",
                server_slug,
                name,
                exc,
                exc_info=True,
            )
            return error_output(
                f"Failed to fetch MCP prompt '{name}': {exc}",
                suggestion="Verify the prompt name and arguments are correct.",
            )

    return _executor
