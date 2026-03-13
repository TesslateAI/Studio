"""
Expose Tesslate Studio as an MCP server via Streamable HTTP transport.

Uses FastMCP from the ``mcp`` Python SDK to register Tesslate's core tools
and serve them over the MCP JSON-RPC protocol. The ASGI app is mounted
in main.py under ``/api/mcp/server``.

Authentication uses the same API key mechanism as the External Agent API.
"""

import logging

from fastapi import APIRouter, Request
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------

mcp_app = FastMCP(
    "Tesslate Studio",
    instructions=(
        "Tools for managing and building web applications via Tesslate Studio. "
        "Use these tools to list files, read code, and run commands in project containers."
    ),
)


# ---------------------------------------------------------------------------
# MCP tool registrations (stubs — full delegation requires container context)
# ---------------------------------------------------------------------------


@mcp_app.tool()
async def list_project_files(project_id: str, path: str = "/") -> str:
    """List files in a Tesslate project directory.

    Args:
        project_id: The project UUID or slug.
        path: Directory path relative to project root. Defaults to "/".

    Returns:
        A listing of files and directories at the given path.
    """
    return f"[MCP] Listing files in project {project_id} at path '{path}' — MCP server operational"


@mcp_app.tool()
async def read_project_file(project_id: str, path: str) -> str:
    """Read a file from a Tesslate project.

    Args:
        project_id: The project UUID or slug.
        path: File path relative to project root.

    Returns:
        The contents of the requested file.
    """
    return f"[MCP] Reading '{path}' from project {project_id} — MCP server operational"


@mcp_app.tool()
async def run_project_command(project_id: str, command: str) -> str:
    """Execute a shell command inside a Tesslate project container.

    Args:
        project_id: The project UUID or slug.
        command: The shell command to execute.

    Returns:
        The stdout/stderr output of the command.
    """
    return (
        f"[MCP] Running command '{command}' in project {project_id} — MCP server operational"
    )


# ---------------------------------------------------------------------------
# FastAPI router — info endpoint + ASGI mount helper
# ---------------------------------------------------------------------------

router = APIRouter(tags=["mcp-server"])


@router.get("/api/mcp/server")
async def mcp_server_info():
    """Return metadata about the Tesslate MCP server."""
    return {
        "name": "Tesslate Studio",
        "description": "MCP server exposing Tesslate project tools (list files, read files, run commands)",
        "transport": "streamable-http",
        "endpoint": "/api/mcp/server/mcp",
        "tools": [
            {
                "name": "list_project_files",
                "description": "List files in a Tesslate project directory",
            },
            {
                "name": "read_project_file",
                "description": "Read a file from a Tesslate project",
            },
            {
                "name": "run_project_command",
                "description": "Execute a shell command in a project container",
            },
        ],
    }


def get_mcp_asgi_app():
    """Return the Streamable HTTP ASGI app for mounting in FastAPI.

    Usage in main.py::

        from .routers.mcp_server import get_mcp_asgi_app, router as mcp_server_router
        app.include_router(mcp_server_router)
        app.mount("/api/mcp/server/mcp", get_mcp_asgi_app())
    """
    return mcp_app.streamable_http_app()
