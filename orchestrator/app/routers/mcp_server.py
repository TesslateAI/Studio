"""
Expose Tesslate Studio as an MCP server via Streamable HTTP transport.

Uses FastMCP from the ``mcp`` Python SDK to register Tesslate's core tools
and serve them over the MCP JSON-RPC protocol. The ASGI app is mounted
in main.py under ``/api/mcp/server``.
"""

import logging
from uuid import UUID

from fastapi import APIRouter
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------

mcp_app = FastMCP(
    "Tesslate Studio",
    stateless_http=True,
    json_response=True,
    instructions=(
        "Tools for managing and building web applications via Tesslate Studio. "
        "Use these tools to list files, read code, and run commands in project containers."
    ),
)

# Mount at root of wherever Starlette mounts us (e.g. /api/mcp/server)
mcp_app.settings.streamable_http_path = "/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_project(project_id: str):
    """Resolve project_id (slug or UUID) to (project, orchestrator) tuple."""
    from ..config import get_settings
    from ..database import AsyncSessionLocal
    from ..models import Container, Project

    settings = get_settings()

    async with AsyncSessionLocal() as db:
        # Try UUID first, then slug
        try:
            pid = UUID(project_id)
            result = await db.execute(select(Project).where(Project.id == pid))
        except ValueError:
            result = await db.execute(select(Project).where(Project.slug == project_id))

        project = result.scalar_one_or_none()
        if not project:
            return None, None, None

        # Get first container for the project
        container_result = await db.execute(
            select(Container)
            .where(Container.project_id == project.id)
            .order_by(Container.created_at)
            .limit(1)
        )
        container = container_result.scalar_one_or_none()
        container_name = container.name if container else "frontend"

        if settings.deployment_mode == "kubernetes":
            from ..services.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
            return project, container_name, KubernetesOrchestrator()
        else:
            from ..services.orchestration.docker import DockerComposeOrchestrator
            return project, container_name, DockerComposeOrchestrator()


# ---------------------------------------------------------------------------
# MCP tool registrations
# ---------------------------------------------------------------------------


@mcp_app.tool()
async def list_project_files(project_id: str, path: str = "/") -> dict:
    """List files in a Tesslate project directory.

    Args:
        project_id: The project UUID or slug.
        path: Directory path relative to project root. Defaults to "/".

    Returns:
        A listing of files and directories at the given path.
    """
    project, container_name, orchestrator = await _resolve_project(project_id)
    if not project:
        return {"error": f"Project '{project_id}' not found"}

    try:
        files = await orchestrator.list_files(
            project.owner_id, project.id, container_name, path
        )
        return {"project_id": str(project.id), "path": path, "files": files}
    except Exception as e:
        logger.error("MCP list_project_files failed: %s", e)
        return {"error": str(e), "project_id": project_id, "path": path}


@mcp_app.tool()
async def read_project_file(project_id: str, path: str) -> dict:
    """Read a file from a Tesslate project.

    Args:
        project_id: The project UUID or slug.
        path: File path relative to project root.

    Returns:
        The contents of the requested file.
    """
    project, container_name, orchestrator = await _resolve_project(project_id)
    if not project:
        return {"error": f"Project '{project_id}' not found"}

    try:
        content = await orchestrator.read_file(
            project.owner_id, project.id, container_name, path,
            project_slug=project.slug,
        )
        if content is None:
            return {"error": f"File '{path}' not found", "project_id": str(project.id)}
        return {"project_id": str(project.id), "path": path, "content": content}
    except Exception as e:
        logger.error("MCP read_project_file failed: %s", e)
        return {"error": str(e), "project_id": project_id, "path": path}


@mcp_app.tool()
async def run_project_command(project_id: str, command: str) -> dict:
    """Execute a shell command inside a Tesslate project container.

    Args:
        project_id: The project UUID or slug.
        command: The shell command to execute.

    Returns:
        The stdout/stderr output of the command.
    """
    project, container_name, orchestrator = await _resolve_project(project_id)
    if not project:
        return {"error": f"Project '{project_id}' not found"}

    try:
        result = await orchestrator.execute_command(
            project.owner_id, project.id, container_name, command,
        )
        return {"project_id": str(project.id), "command": command, "output": result}
    except Exception as e:
        logger.error("MCP run_project_command failed: %s", e)
        return {"error": str(e), "project_id": project_id, "command": command}


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
        app.mount("/api/mcp/server", get_mcp_asgi_app())
    """
    return mcp_app.streamable_http_app()
