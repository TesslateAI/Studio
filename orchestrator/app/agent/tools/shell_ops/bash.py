"""
Bash Convenience Tool

One-shot command execution for volume-first projects.
Returns immediately when the command exits — no PTY session, no sleep.

Tier 1 (ephemeral): ComputeManager ephemeral pods for quick commands.
Tier 2 (environment): kubectl exec into running dev containers.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


def _has_volume_hints(context: dict[str, Any]) -> bool:
    """Check if the context includes volume routing hints (required for K8s execution)."""
    volume_id = context.get("volume_id")
    cache_node = context.get("cache_node")
    return volume_id is not None and cache_node is not None


async def _run_ephemeral(context: dict[str, Any], command: str, timeout: int) -> dict[str, Any]:
    """Execute a command via ComputeManager ephemeral pod (Tier 1)."""
    from ....database import AsyncSessionLocal
    from ....models import Project
    from ....services.compute_manager import ComputeQuotaExceeded, get_compute_manager

    volume_id = context["volume_id"]
    node_name = context["cache_node"]
    project_id = context["project_id"]

    compute = get_compute_manager()

    # Mark compute state in an isolated transaction (don't hold the agent session open)
    async def _set_compute_state(tier: str, pod: str | None = None) -> None:
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project:
                project.compute_tier = tier
                project.active_compute_pod = pod
                if tier != "none":
                    project.last_activity = datetime.now(UTC)
                await db.commit()

    await _set_compute_state("ephemeral")

    try:
        try:
            output, exit_code, pod_name = await compute.run_command(
                volume_id=volume_id,
                node_name=node_name,
                command=["/bin/sh", "-c", command],
                timeout=timeout,
            )
        except ComputeQuotaExceeded:
            return error_output(
                message="Compute pool quota exceeded — too many concurrent commands",
                suggestion="Wait a moment and retry, or start a full environment with project start",
                details={"command": command, "tier": "ephemeral"},
            )

        clean_output = strip_ansi_codes(output) if output else ""

        if exit_code == 124:
            return error_output(
                message=f"Command timed out after {timeout}s: {command}",
                suggestion="Try a shorter command or increase the timeout parameter",
                details={
                    "command": command,
                    "timeout": timeout,
                    "exit_code": 124,
                    "tier": "ephemeral",
                },
            )

        if exit_code != 0:
            return error_output(
                message=f"Command failed (exit code {exit_code}): {command}",
                suggestion="Check the output for errors",
                details={
                    "command": command,
                    "exit_code": exit_code,
                    "output": clean_output,
                    "tier": "ephemeral",
                },
            )

        logger.info("[BASH-V2] Command completed, output_length=%d", len(clean_output))
        return success_output(
            message=f"Executed '{command}'",
            output=clean_output,
            details={"command": command, "exit_code": 0, "tier": "ephemeral"},
        )

    finally:
        await _set_compute_state("none")


def _get_k8s_api():
    """Get or create a cached CoreV1Api for Tier 2 exec (matches T1 lazy-init pattern)."""
    if not hasattr(_get_k8s_api, "_v1"):
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        from kubernetes import client as k8s_client

        _get_k8s_api._v1 = k8s_client.CoreV1Api()
    return _get_k8s_api._v1


async def _find_dev_pod(context: dict[str, Any]) -> tuple[Any | None, dict[str, Any] | None]:
    """Find the running dev container pod for a project.

    Returns (pod, None) on success or (None, error_dict) on failure.
    """
    import asyncio

    from kubernetes.client.rest import ApiException as K8sApiException

    project_id = context["project_id"]
    namespace = f"proj-{project_id}"
    container_name = context.get("container_name")

    v1 = _get_k8s_api()

    labels = "tesslate.io/tier=2,tesslate.io/component=dev-container"
    if container_name:
        safe_name = container_name.lower().replace(" ", "-").replace("_", "-")
        labels += f",tesslate.io/container-directory={safe_name}"

    try:
        pod_list = await asyncio.to_thread(
            v1.list_namespaced_pod,
            namespace,
            label_selector=labels,
            field_selector="status.phase=Running",
        )
    except K8sApiException as exc:
        if exc.status == 404:
            return None, error_output(
                message="Project namespace not found — environment may not be started",
                suggestion="Start the project environment first",
                details={"namespace": namespace, "tier": "environment"},
            )
        raise

    pods = pod_list.items or []
    if not pods and container_name:
        try:
            pod_list = await asyncio.to_thread(
                v1.list_namespaced_pod,
                namespace,
                label_selector="tesslate.io/tier=2,tesslate.io/component=dev-container",
                field_selector="status.phase=Running",
            )
            pods = pod_list.items or []
        except K8sApiException:
            pass

    if not pods:
        return None, error_output(
            message="No running dev container found in the environment",
            suggestion="Start the project environment or wait for pods to be ready",
            details={"namespace": namespace, "tier": "environment"},
        )

    return pods[0], None


async def _run_via_tsinit(pod_ip: str, command: str, timeout: int) -> tuple[str, str, int] | None:
    """Try executing a command via tsinit's /v1/run WebSocket endpoint.

    Returns (stdout, stderr, exit_code) on success, or None if tsinit
    is not reachable (caller should fall back to kubectl exec).
    """
    from ....services.tsinit_client import TsinitClient

    client = TsinitClient(host=pod_ip)
    if not await client.is_reachable(timeout=2.0):
        return None

    return await client.run(cmd=command, tty=False, timeout=timeout)


async def _run_environment(context: dict[str, Any], command: str, timeout: int) -> dict[str, Any]:
    """Execute a command in a running Tier 2 dev container.

    Tries tsinit WebSocket first (structured exit codes, clean stdout/stderr
    separation). Falls back to kubectl exec if tsinit is not reachable.
    """
    pod, err = await _find_dev_pod(context)
    if err is not None:
        return err

    pod_name = pod.metadata.name
    pod_ip = pod.status.pod_ip

    # --- Fast path: tsinit WebSocket ---
    if pod_ip:
        result = await _run_via_tsinit(pod_ip, command, timeout)
        if result is not None:
            stdout, stderr, exit_code = result
            clean_output = strip_ansi_codes(stdout) if stdout else ""
            if stderr:
                clean_output = clean_output + strip_ansi_codes(stderr)

            if exit_code == 124:
                return error_output(
                    message=f"Command timed out after {timeout}s: {command}",
                    suggestion="Try a shorter command or increase the timeout parameter",
                    details={
                        "command": command,
                        "timeout": timeout,
                        "exit_code": 124,
                        "tier": "environment",
                    },
                )

            if exit_code != 0:
                return error_output(
                    message=f"Command failed (exit code {exit_code}): {command}",
                    suggestion="Check the output for errors",
                    details={
                        "command": command,
                        "exit_code": exit_code,
                        "output": clean_output,
                        "pod": pod_name,
                        "tier": "environment",
                    },
                )

            logger.info(
                "[BASH-ENV] tsinit command completed in %s, output_length=%d",
                pod_name,
                len(clean_output),
            )
            return success_output(
                message=f"Executed '{command}'",
                output=clean_output,
                details={
                    "command": command,
                    "exit_code": 0,
                    "pod": pod_name,
                    "tier": "environment",
                },
            )

    # --- Fallback: kubectl exec with sentinel exit code parsing ---
    logger.info("[BASH-ENV] tsinit not reachable, falling back to kubectl exec for %s", pod_name)
    return await _run_environment_kubectl(context, pod_name, command, timeout)


async def _run_environment_kubectl(
    context: dict[str, Any], pod_name: str, command: str, timeout: int
) -> dict[str, Any]:
    """Execute via kubectl exec (legacy fallback when tsinit is unavailable)."""
    import asyncio

    from kubernetes.client.rest import ApiException as K8sApiException
    from kubernetes.stream import stream as k8s_stream

    project_id = context["project_id"]
    namespace = f"proj-{project_id}"
    v1 = _get_k8s_api()

    wrapped_command = f'{command}\n__EXIT_CODE__=$?\necho "__TESSLATE_EXIT:$__EXIT_CODE__"'
    exec_command = ["/bin/sh", "-c", wrapped_command]

    try:
        output = await asyncio.to_thread(
            k8s_stream,
            v1.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            container="dev-server",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _request_timeout=timeout,
        )
    except K8sApiException as exc:
        return error_output(
            message=f"Failed to exec in pod {pod_name}: {exc.reason}",
            suggestion="Check if the dev container is running and ready",
            details={
                "pod": pod_name,
                "namespace": namespace,
                "error": str(exc),
                "tier": "environment",
            },
        )
    except Exception as exc:
        return error_output(
            message=f"Command execution failed: {exc}",
            suggestion="Check if the environment is healthy",
            details={"pod": pod_name, "command": command, "error": str(exc), "tier": "environment"},
        )

    raw_output = output or ""
    exit_code = 0
    sentinel = "__TESSLATE_EXIT:"
    if sentinel in raw_output:
        parts = raw_output.rsplit(sentinel, 1)
        raw_output = parts[0]
        try:  # noqa: SIM105
            exit_code = int(parts[1].strip())
        except (ValueError, IndexError):
            pass

    clean_output = strip_ansi_codes(raw_output) if raw_output else ""

    if exit_code != 0:
        return error_output(
            message=f"Command failed (exit code {exit_code}): {command}",
            suggestion="Check the output for errors",
            details={
                "command": command,
                "exit_code": exit_code,
                "output": clean_output,
                "pod": pod_name,
                "tier": "environment",
            },
        )

    logger.info(
        "[BASH-ENV] kubectl exec completed in %s, output_length=%d", pod_name, len(clean_output)
    )
    return success_output(
        message=f"Executed '{command}'",
        output=clean_output,
        details={"command": command, "exit_code": 0, "pod": pod_name, "tier": "environment"},
    )


async def _run_docker(context: dict[str, Any], command: str, timeout: int) -> dict[str, Any]:
    """Execute a command via the Docker orchestrator's execute_command."""
    from ....services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()
    project_id = context.get("project_id")
    user_id = context.get("user_id")
    container_name = context.get("container_name")

    try:
        output = await orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=["bash", "-c", command],
            timeout=timeout,
        )
        clean_output = strip_ansi_codes(output) if output else ""
        return success_output(
            message=f"Executed '{command}'",
            output=clean_output,
            details={"command": command, "exit_code": 0, "tier": "docker"},
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[BASH-DOCKER] Command failed: {error_msg}")
        return error_output(
            message=f"Command failed: {error_msg}",
            suggestion="Check if the container is running and the command is valid",
            details={"command": command},
        )


async def bash_exec_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a single command via the orchestrator's one-shot execute_command.

    Uses asyncio subprocess (Docker) or K8s exec API (Kubernetes) — both return
    immediately on process exit with stdout+stderr combined. No PTY, no sleep.

    Args:
        params: {
            command: str,      # Command to execute
            timeout: int       # Max seconds to wait (default: 120)
        }
        context: {user_id: UUID, project_id: str, db: AsyncSession, container_name: str?}

    Returns:
        Dict with command output and exit code info
    """
    command = params.get("command")
    timeout = int(params.get("timeout", 120))

    if not command:
        raise ValueError("command parameter is required")

    logger.info(f"[BASH] Executing (one-shot): {command[:100]}...")

    # Docker mode: delegate to orchestrator.execute_command
    from ....config import get_settings

    settings = get_settings()
    if settings.is_docker_mode:
        return await _run_docker(context, command, timeout)

    # K8s mode: requires volume routing hints for pod scheduling
    if not _has_volume_hints(context):
        return error_output(
            message="Missing volume routing hints — cannot execute command",
            suggestion="Ensure the project has a valid volume_id and cache_node",
            details={"command": command},
        )

    if context.get("compute_tier") == "environment":
        return await _run_environment(context, command, timeout)
    return await _run_ephemeral(context, command, timeout)


def register_bash_tools(registry):
    """Register bash convenience tools."""

    registry.register(
        Tool(
            name="bash_exec",
            description="Execute a bash/sh command and return its output. The command runs to completion and returns stdout+stderr. For interactive sessions, use shell_open + shell_exec instead.",
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute (e.g., 'npm install', 'ls -la', 'cat package.json')",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum seconds to wait for the command to finish (default: 120)",
                        "default": 120,
                    },
                },
                "required": ["command"],
            },
            executor=bash_exec_tool,
            examples=[
                '{"tool_name": "bash_exec", "parameters": {"command": "npm install"}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "ls -la", "timeout": 30}}',
            ],
        )
    )

    logger.info("Registered 1 bash convenience tool")
