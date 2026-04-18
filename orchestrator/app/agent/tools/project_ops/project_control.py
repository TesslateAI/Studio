"""Project Control Tool — container observation from the code view.

Read-only inspection of the project's containers. Lifecycle actions (start,
stop, restart, apply config) moved out into dedicated tools:

  * ``apply_setup_config``  — write config.json + sync the full graph
  * ``project_start/stop/restart`` — whole-project lifecycle
  * ``container_start/stop/restart`` — single-container lifecycle

What remains here is pure observation:

  * ``status``          — list containers with running state and URLs
  * ``container_logs``  — tail the last 100 lines from a container
  * ``health_check``    — HTTP probe against a container's dev-server port
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ._helpers import (
    fetch_all_containers,
    lookup_container_by_name,
    require_project_context,
    resolve_container_dir,
)

logger = logging.getLogger(__name__)

# Maximum bytes returned from container_logs to avoid blowing up context.
_MAX_LOG_BYTES = 50 * 1024  # 50 KB
_LOG_TAIL_LINES = 100


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


async def _action_status(context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import get_orchestrator

    containers = await fetch_all_containers(db, project_id)
    if not containers:
        return success_output(message="No containers in this project", containers=[])

    orchestrator = get_orchestrator()
    status = await orchestrator.get_project_status(project_slug, project_id)

    status_map = status.get("containers", {})
    container_list = []
    for container in containers:
        cid = str(container.id)
        container_status: dict[str, Any] = {}
        for _dir_key, info in status_map.items():
            if info.get("container_id") == cid:
                container_status = info
                break

        container_list.append(
            {
                "name": container.name,
                "directory": container.directory,
                "status": "running" if container_status.get("running") else "stopped",
                "url": container_status.get("url"),
                "port": container.effective_port,
            }
        )

    return success_output(
        message=f"Found {len(containers)} container(s)",
        project_status=status.get("status", "unknown"),
        containers=container_list,
    )


async def _action_container_logs(
    container_name: str, context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import is_kubernetes_mode

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            suggestion="Use the 'status' action to list available container names",
        )

    dir_key = await resolve_container_dir(project_id, container)

    if is_kubernetes_mode():
        namespace = f"proj-{project_id}"
        pod_prefix = f"dev-{dir_key}"
        cmd = (
            f"kubectl --context=tesslate logs -n {namespace} "
            f"-l app={pod_prefix} --tail={_LOG_TAIL_LINES} --timestamps"
        )
    else:
        # Docker Compose service naming: {slug}-{container_name}-1
        service = f"{project_slug}-{container_name}-1"
        cmd = f"docker logs {service} --tail={_LOG_TAIL_LINES}"

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except TimeoutError:
        return error_output(
            message=f"Timed out fetching logs for '{container_name}'",
            suggestion="The container may be unresponsive — try restarting it",
        )
    except Exception as exc:
        return error_output(
            message=f"Failed to fetch logs: {exc}",
            suggestion="Ensure the container is running",
        )

    output = (stdout or b"") + (stderr or b"")
    if len(output) > _MAX_LOG_BYTES:
        output = output[-_MAX_LOG_BYTES:]

    logs_text = output.decode("utf-8", errors="replace")

    return success_output(
        message=f"Last logs for '{container_name}'",
        container_name=container_name,
        logs=logs_text,
    )


async def _action_health_check(
    container_name: str, context: dict[str, Any]
) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import is_kubernetes_mode

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            suggestion="Use the 'status' action to list available container names",
        )

    port = container.effective_port
    dir_key = await resolve_container_dir(project_id, container)

    if is_kubernetes_mode():
        namespace = f"proj-{project_id}"
        url = f"http://dev-{dir_key}.{namespace}.svc.cluster.local:{port}"
    else:
        url = f"http://{project_slug}-{container_name}.localhost"

    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
        return success_output(
            message=f"Health check for '{container_name}'",
            container_name=container_name,
            healthy=resp.status_code < 500,
            status_code=resp.status_code,
            url=url,
        )
    except httpx.ConnectError as exc:
        return success_output(
            message=f"Health check for '{container_name}' — connection refused",
            container_name=container_name,
            healthy=False,
            status_code=None,
            url=url,
            error=str(exc),
        )
    except Exception as exc:
        return success_output(
            message=f"Health check for '{container_name}' — error",
            container_name=container_name,
            healthy=False,
            status_code=None,
            url=url,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

_ACTIONS_REQUIRING_CONTAINER = {"container_logs", "health_check"}

parameters = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["status", "container_logs", "health_check"],
            "description": "Observation action to perform.",
        },
        "container_name": {
            "type": "string",
            "description": (
                "Name of the container (from .tesslate/config.json). "
                "Required for container_logs and health_check."
            ),
        },
    },
    "required": ["action"],
}


async def project_control_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch an observation action."""
    action = params.get("action")
    container_name = params.get("container_name")

    if not action:
        return error_output(
            message="'action' parameter is required",
            suggestion="Choose one of: status, container_logs, health_check",
        )

    if require_project_context(context) is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )

    if action in _ACTIONS_REQUIRING_CONTAINER and not container_name:
        return error_output(
            message=f"'container_name' is required for the '{action}' action",
            suggestion="Pass the container name from .tesslate/config.json",
        )

    try:
        if action == "status":
            return await _action_status(context)
        elif action == "container_logs":
            assert container_name is not None
            return await _action_container_logs(container_name, context)
        elif action == "health_check":
            assert container_name is not None
            return await _action_health_check(container_name, context)
        else:
            return error_output(
                message=f"Unknown action '{action}'",
                suggestion=(
                    "Choose one of: status, container_logs, health_check. "
                    "For lifecycle actions use project_start/stop/restart, "
                    "container_start/stop/restart, or apply_setup_config."
                ),
            )
    except Exception as exc:
        logger.error(
            "project_control action '%s' failed: %s", action, exc, exc_info=True
        )
        return error_output(
            message=f"Action '{action}' failed: {exc}",
            suggestion="Check container configuration and try again",
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_project_control_tools(registry):
    """Register the observation-only project_control tool."""
    registry.register(
        Tool(
            name="project_control",
            description=(
                "Observe the project's containers: status, logs, and health checks. "
                "For starting/stopping/restarting use project_start/project_stop/"
                "project_restart or container_start/container_stop/container_restart. "
                "For config changes use apply_setup_config."
            ),
            category=ToolCategory.PROJECT,
            parameters=parameters,
            executor=project_control_executor,
            examples=[
                '{"tool_name": "project_control", "parameters": {"action": "status"}}',
                '{"tool_name": "project_control", "parameters": {"action": "container_logs", "container_name": "frontend"}}',
                '{"tool_name": "project_control", "parameters": {"action": "health_check", "container_name": "backend"}}',
            ],
        )
    )
