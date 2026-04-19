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
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_container_dir(project_id, container) -> str:
    """Resolve the K8s deployment directory key for *container*.

    Reads live pod labels (source of truth) first; falls back to the
    centralised helper that sanitises ``container.directory``.
    """
    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    if is_kubernetes_mode():
        try:
            orchestrator = get_orchestrator()
            status = await orchestrator.get_project_status("", project_id)
            cid = str(container.id)
            for dir_key, info in status.get("containers", {}).items():
                if info.get("container_id") == cid:
                    return dir_key
        except Exception:
            logger.debug(
                "K8s status lookup failed for container %s, using fallback",
                container.id,
                exc_info=True,
            )

    from ....services.compute_manager import resolve_k8s_container_dir

    return resolve_k8s_container_dir(container)


async def _lookup_container_by_name(db, project_id, container_name: str):
    """Return a Container model matched by name, or ``None``."""
    from sqlalchemy import select

    from ....models import Container

    result = await db.execute(
        select(Container).where(
            Container.name == container_name,
            Container.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_available_names(db, project_id) -> list[str]:
    """Return the names of all containers in the project (for error messages)."""
    from sqlalchemy import select

    from ....models import Container

    result = await db.execute(select(Container.name).where(Container.project_id == project_id))
    return [row[0] for row in result.all()]


def _is_local_mode() -> bool:
    """Return True when running in desktop/local mode (no docker compose, no kubectl)."""
    from ....config import get_settings
    from ....services.orchestration import is_kubernetes_mode

    if is_kubernetes_mode():
        return False
    mode = (get_settings().deployment_mode or "").lower()
    return mode in ("desktop", "local")


async def _fetch_project(db, project_id):
    """Return the Project model for *project_id*, or ``None``."""
    from sqlalchemy import select

    from ....models import Project

    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def _fetch_all_containers(db, project_id):
    """Return all Container models (with base eagerly loaded) for the project."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from ....models import Container

    result = await db.execute(
        select(Container)
        .where(Container.project_id == project_id)
        .options(selectinload(Container.base))
    )
    return result.scalars().all()


async def _fetch_connections(db, project_id):
    """Return all ContainerConnection models for the project."""
    from sqlalchemy import select

    from ....models import ContainerConnection

    result = await db.execute(
        select(ContainerConnection).where(ContainerConnection.project_id == project_id)
    )
    return result.scalars().all()


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

    from ....services.compute_manager import resolve_k8s_container_dir

    status_map = status.get("containers", {})
    container_list = []
    for container in containers:
        cid = str(container.id)
        dir_key = resolve_k8s_container_dir(container)
        container_status: dict[str, Any] = {}
        # Prefer matching by container_id in values (K8s / local modes set this).
        for _key, info in status_map.items():
            if info.get("container_id") == cid:
                container_status = info
                break
        # Fallback: Docker compose sets service_name as the map key directly.
        if not container_status:
            container_status = status_map.get(dir_key, {})

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


async def _action_tier_status(context: dict[str, Any]) -> dict[str, Any]:
    """Report compute-tier state: which tier, pod name, env status, containers.

    Read-only snapshot of ``Project.compute_tier`` + ``active_compute_pod`` +
    ``environment_status`` + ``last_activity`` plus the per-container status
    list. No K8s API calls — everything comes from the DB.
    """
    db = context["db"]
    project_id = context["project_id"]

    project = await _fetch_project(db, project_id)
    if project is None:
        return error_output(
            message="Project not found",
            suggestion="Ensure the tool is called within a valid project session",
        )

    containers = await _fetch_all_containers(db, project_id)
    container_list = [
        {
            "name": c.name,
            "directory": c.directory,
            "status": c.status,
            "ready": c.status == "running",
            "is_primary": c.is_primary is True,
            "container_type": c.container_type,
        }
        for c in containers
    ]

    namespace = f"proj-{project_id}" if project.compute_tier == "environment" else None
    last_activity = project.last_activity.isoformat() if project.last_activity is not None else None

    return success_output(
        message=f"Compute tier: {project.compute_tier}",
        compute_tier=project.compute_tier,
        active_compute_pod=project.active_compute_pod,
        environment_status=project.environment_status,
        last_activity=last_activity,
        namespace=namespace,
        containers=container_list,
    )


async def _action_restart_container(container_name: str, context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    user_id = context["user_id"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    container = await _lookup_container_by_name(db, project_id, container_name)
    if not container:
        available = await _get_available_names(db, project_id)
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            available_containers=available,
            suggestion=f"Available containers: {available}",
        )

    project = await _fetch_project(db, project_id)
    if not project:
        return error_output(
            message="Project not found",
            suggestion="Ensure you are in a valid project context",
        )

    if project.environment_status == "provisioning":
        return error_output(
            message="Project is still being provisioned. Wait for setup to complete before restarting containers.",
            suggestion="Try again in a moment.",
        )

    orchestrator = get_orchestrator()

    # --- Stop ---
    dir_key = await _resolve_container_dir(project_id, container)
    stop_kwargs: dict[str, Any] = {
        "project_slug": project_slug,
        "project_id": project_id,
        "container_name": dir_key,
        "user_id": user_id,
    }
    if is_kubernetes_mode() and getattr(container, "container_type", "base") == "service":
        stop_kwargs["container_type"] = "service"
        stop_kwargs["service_slug"] = container.service_slug

    try:
        await orchestrator.stop_container(**stop_kwargs)
    except Exception as exc:
        logger.warning("stop_container failed for %s: %s", container_name, exc)
        # Continue to start — the container may already be stopped.

    # --- Start ---
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from ....models import Container as ContainerModel

    # Re-fetch with base loaded (needed by start_container)
    fresh = await db.execute(
        select(ContainerModel)
        .where(ContainerModel.id == container.id)
        .options(selectinload(ContainerModel.base))
    )
    container = fresh.scalar_one()

    all_containers = await _fetch_all_containers(db, project_id)
    connections = await _fetch_connections(db, project_id)

    result = await orchestrator.start_container(
        project=project,
        container=container,
        all_containers=all_containers,
        connections=connections,
        user_id=user_id,
        db=db,
    )

    return success_output(
        message=f"Container '{container_name}' restarted successfully",
        container_name=container_name,
        url=result.get("url"),
        status="starting",
    )


async def _action_restart_all(context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    user_id = context["user_id"]
    project_id = context["project_id"]

    from ....services.orchestration import get_orchestrator

    project = await _fetch_project(db, project_id)
    if not project:
        return error_output(
            message="Project not found",
            suggestion="Ensure you are in a valid project context",
        )

    if project.environment_status == "provisioning":
        return error_output(
            message="Project is still being provisioned. Wait for setup to complete before restarting containers.",
            suggestion="Try again in a moment.",
        )

    containers = await _fetch_all_containers(db, project_id)
    if not containers:
        return error_output(
            message="No containers in this project",
            suggestion="Add containers to the project first",
        )

    connections = await _fetch_connections(db, project_id)

    orchestrator = get_orchestrator()
    await orchestrator.restart_project(project, containers, connections, user_id, db)

    return success_output(
        message=f"Restarted all {len(containers)} container(s)",
        container_count=len(containers),
    )


async def _action_reload_config(context: dict[str, Any]) -> dict[str, Any]:
    """Re-read .tesslate/config.json and sync Container DB records."""
    user_id = context["user_id"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    # Read the config file from the project filesystem.
    raw: str | None = None
    try:
        raw = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=".",
            file_path=".tesslate/config.json",
            project_slug=project_slug,
            subdir=".",
            volume_id=context.get("volume_id"),
        )
    except Exception as exc:
        logger.warning("read_file for .tesslate/config.json failed: %s", exc)

    if not raw:
        return error_output(
            message="Could not read .tesslate/config.json",
            suggestion="Ensure the file exists inside the project",
        )

    from ....services.base_config_parser import parse_tesslate_config

    try:
        config = parse_tesslate_config(raw)
    except ValueError as exc:
        return error_output(
            message=f"Invalid .tesslate/config.json: {exc}",
            suggestion="Fix the config file syntax and try again",
        )

    if not config.apps and not config.infrastructure:
        return error_output(
            message=".tesslate/config.json has no apps or infrastructure entries",
            suggestion="Add at least one app entry to the config",
        )

    # Sync containers inside a dedicated session (same pattern as read_write.py).
    from ....database import AsyncSessionLocal
    from ....models import Container

    synced = 0
    try:
        async with AsyncSessionLocal() as sync_db:
            from sqlalchemy import select

            existing_result = await sync_db.execute(
                select(Container).where(Container.project_id == project_id)
            )
            existing = {c.name: c for c in existing_result.scalars().all()}

            # --- App containers ---
            for app_name, app_cfg in config.apps.items():
                if app_name in existing:
                    c = existing[app_name]
                    c.directory = app_cfg.directory
                    c.internal_port = app_cfg.port or 3000
                    c.startup_command = app_cfg.start or c.startup_command
                    c.environment_vars = app_cfg.env or {}
                    del existing[app_name]
                else:
                    c = Container(
                        project_id=project_id,
                        name=app_name,
                        directory=app_cfg.directory,
                        container_name=f"{project_slug}-{app_name}",
                        internal_port=app_cfg.port or 3000,
                        startup_command=app_cfg.start or None,
                        environment_vars=app_cfg.env or {},
                        container_type="base",
                        status="stopped",
                        position_x=app_cfg.x or 200,
                        position_y=app_cfg.y or 200,
                    )
                    sync_db.add(c)
                synced += 1

            # --- Infrastructure containers ---
            for infra_name, infra_cfg in config.infrastructure.items():
                if infra_name in existing:
                    c = existing[infra_name]
                    c.internal_port = infra_cfg.port
                    c.environment_vars = infra_cfg.env or {}
                    del existing[infra_name]
                else:
                    c = Container(
                        project_id=project_id,
                        name=infra_name,
                        directory=".",
                        container_name=f"{project_slug}-{infra_name}",
                        internal_port=infra_cfg.port,
                        environment_vars=infra_cfg.env or {},
                        container_type="service",
                        status="stopped",
                        position_x=infra_cfg.x or 400,
                        position_y=infra_cfg.y or 200,
                    )
                    sync_db.add(c)
                synced += 1

            # Delete orphaned base containers that are no longer in config.
            for orphan in existing.values():
                if orphan.container_type == "base":
                    await sync_db.delete(orphan)

            await sync_db.commit()
            logger.info("[project_control] Synced %d containers from config", synced)
    except Exception as exc:
        logger.error("Failed to sync containers from config: %s", exc, exc_info=True)
        return error_output(
            message=f"Failed to sync containers: {exc}",
            suggestion="Check database connectivity and try again",
        )

    return success_output(
        message=f"Reloaded config and synced {synced} container(s)",
        synced_count=synced,
    )


async def _action_container_logs(container_name: str, context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import is_kubernetes_mode

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        available = await _get_available_names(db, project_id)
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            available_containers=available,
            suggestion=f"Available containers: {available}",
        )

    dir_key = await resolve_container_dir(project_id, container)

    if _is_local_mode():
        # Local/desktop: read from the PTY session history — no docker or kubectl.
        from ....services.orchestration.local import _LOCAL_DEV_SERVERS, PTY_SESSIONS

        cid = str(container.id)
        sid = _LOCAL_DEV_SERVERS.get(cid) or _LOCAL_DEV_SERVERS.get(container_name)
        if not sid:
            return error_output(
                message=f"No running session found for '{container_name}'",
                suggestion="Start the container first with the 'restart_container' action",
            )
        try:
            raw = PTY_SESSIONS.read_history(sid, max_bytes=_MAX_LOG_BYTES)
            logs_text = raw.decode("utf-8", errors="replace")
        except KeyError:
            logs_text = "(session ended)"
        return success_output(
            message=f"Last logs for '{container_name}'",
            container_name=container_name,
            logs=logs_text,
        )

    if is_kubernetes_mode():
        namespace = f"proj-{project_id}"
        pod_prefix = f"dev-{dir_key}"
        cmd = (
            f"kubectl --context=tesslate logs -n {namespace} "
            f"-l app={pod_prefix} --tail={_LOG_TAIL_LINES} --timestamps"
        )
    else:
        # Docker Compose service naming uses the directory key, not the container name.
        service = f"{project_slug}-{dir_key}-1"
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


async def _action_health_check(container_name: str, context: dict[str, Any]) -> dict[str, Any]:
    db = context["db"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")

    from ....services.orchestration import is_kubernetes_mode

    container = await lookup_container_by_name(db, project_id, container_name)
    if not container:
        available = await _get_available_names(db, project_id)
        return error_output(
            message=f"Container '{container_name}' not found in this project",
            available_containers=available,
            suggestion=f"Available containers: {available}",
        )

    port = container.effective_port
    dir_key = await resolve_container_dir(project_id, container)

    if is_kubernetes_mode():
        namespace = f"proj-{project_id}"
        url = f"http://dev-{dir_key}.{namespace}.svc.cluster.local:{port}"
    elif _is_local_mode():
        url = f"http://localhost:{port}" if port else ""
    else:
        # Docker Compose: service hostname uses dir_key (same as service name).
        url = f"http://{project_slug}-{dir_key}.localhost"

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
            "enum": ["status", "container_logs", "health_check", "tier_status"],
            "description": (
                "Observation action. 'tier_status' reports compute-tier state "
                "(none / ephemeral / environment) plus pod + container readiness."
            ),
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
        elif action == "tier_status":
            return await _action_tier_status(context)
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
                    "Choose one of: status, tier_status, container_logs, "
                    "health_check. For lifecycle actions use project_start/"
                    "stop/restart, container_start/stop/restart, or "
                    "apply_setup_config."
                ),
            )
    except Exception as exc:
        logger.error("project_control action '%s' failed: %s", action, exc, exc_info=True)
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
                "Observe the project's containers and compute tier. Actions: "
                "'status' (list containers + URLs), 'tier_status' (report "
                "compute_tier / active_compute_pod / environment_status / "
                "per-container readiness — call this before bash_exec with "
                "tier='environment' to confirm the env is up), "
                "'container_logs' (tail 100 lines), 'health_check' (HTTP "
                "probe). For starting/stopping use project_start/project_stop/"
                "project_restart or container_start/container_stop/"
                "container_restart. For config changes use apply_setup_config."
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
