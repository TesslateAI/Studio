"""
Bash Convenience Tool

One-shot command execution using the orchestrator's execute_command method.
Returns immediately when the command exits — no PTY session, no sleep.

v1 (legacy) projects use the orchestrator (Docker exec / K8s exec).
v2 (volume-first) projects use ComputeManager ephemeral pods.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


def _is_v2_project(context: dict[str, Any]) -> bool:
    """Detect v2 volume-first project from context hints."""
    volume_state = context.get("volume_state")
    volume_id = context.get("volume_id")
    node_name = context.get("node_name")
    return (
        volume_state not in ("legacy", None)
        and volume_id is not None
        and node_name is not None
    )


async def _run_v2_ephemeral(
    context: dict[str, Any], command: str, timeout: int
) -> dict[str, Any]:
    """Execute a command via ComputeManager ephemeral pod (Tier 1)."""
    from ....database import AsyncSessionLocal
    from ....models import Project
    from ....services.compute_manager import ComputeQuotaExceeded, get_compute_manager

    volume_id = context["volume_id"]
    node_name = context["node_name"]
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
                    project.last_activity = datetime.now(timezone.utc)
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
                details={"command": command},
            )

        clean_output = strip_ansi_codes(output) if output else ""

        if exit_code == 124:
            return error_output(
                message=f"Command timed out after {timeout}s: {command}",
                suggestion="Try a shorter command or increase the timeout parameter",
                details={"command": command, "timeout": timeout, "exit_code": 124},
            )

        if exit_code != 0:
            return error_output(
                message=f"Command failed (exit code {exit_code}): {command}",
                suggestion="Check the output for errors",
                details={
                    "command": command,
                    "exit_code": exit_code,
                    "output": clean_output,
                },
            )

        logger.info("[BASH-V2] Command completed, output_length=%d", len(clean_output))
        return success_output(
            message=f"Executed '{command}'",
            output=clean_output,
            details={"command": command, "exit_code": 0},
        )

    finally:
        await _set_compute_state("none")


def _get_v2_k8s_api():
    """Get or create a cached CoreV1Api for Tier 2 exec (matches T1 lazy-init pattern)."""
    if not hasattr(_get_v2_k8s_api, "_v1"):
        from kubernetes import config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        from kubernetes import client as k8s_client
        _get_v2_k8s_api._v1 = k8s_client.CoreV1Api()
    return _get_v2_k8s_api._v1


async def _run_v2_environment(
    context: dict[str, Any], command: str, timeout: int
) -> dict[str, Any]:
    """Execute a command in a running Tier 2 dev container via kubectl exec.

    Targets the correct pod using container_name/container_directory from context.
    Captures exit codes via sentinel pattern (k8s_stream doesn't expose them).
    """
    import asyncio
    from kubernetes.client.rest import ApiException as K8sApiException
    from kubernetes.stream import stream as k8s_stream

    project_id = context["project_id"]
    namespace = f"proj-{project_id}"
    container_name = context.get("container_name")

    v1 = _get_v2_k8s_api()

    # Build label selector — target specific container if context provides one
    labels = "tesslate.io/tier=2,tesslate.io/component=dev-container"
    if container_name:
        # Sanitize to match the label value set during deployment
        safe_name = container_name.lower().replace(" ", "-").replace("_", "-")
        labels += f",tesslate.io/container-directory={safe_name}"

    # Find running dev container pod
    try:
        pod_list = await asyncio.to_thread(
            v1.list_namespaced_pod,
            namespace,
            label_selector=labels,
            field_selector="status.phase=Running",
        )
    except K8sApiException as exc:
        if exc.status == 404:
            return error_output(
                message="Project namespace not found — environment may not be started",
                suggestion="Start the project environment first",
                details={"namespace": namespace},
            )
        raise

    pods = pod_list.items or []
    if not pods:
        # If targeting a specific container found nothing, fall back to any dev pod
        if container_name:
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
            return error_output(
                message="No running dev container found in the environment",
                suggestion="Start the project environment or wait for pods to be ready",
                details={"namespace": namespace},
            )

    pod_name = pods[0].metadata.name

    # Wrap command with exit code capture — k8s_stream returns combined stdout+stderr
    # but doesn't expose the process exit code. Use a sentinel to extract it.
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
            details={"pod": pod_name, "namespace": namespace, "error": str(exc)},
        )
    except Exception as exc:
        return error_output(
            message=f"Command execution failed: {exc}",
            suggestion="Check if the environment is healthy",
            details={"pod": pod_name, "command": command, "error": str(exc)},
        )

    # Parse exit code from sentinel
    raw_output = output or ""
    exit_code = 0
    sentinel = "__TESSLATE_EXIT:"
    if sentinel in raw_output:
        parts = raw_output.rsplit(sentinel, 1)
        raw_output = parts[0]
        try:
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
            },
        )

    logger.info("[BASH-V2-ENV] Command completed in %s, output_length=%d", pod_name, len(clean_output))
    return success_output(
        message=f"Executed '{command}'",
        output=clean_output,
        details={"command": command, "exit_code": 0, "pod": pod_name},
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

    # v2 volume-first projects
    if _is_v2_project(context):
        if context.get("compute_tier") == "environment":
            return await _run_v2_environment(context, command, timeout)
        return await _run_v2_ephemeral(context, command, timeout)

    # v1 legacy path — orchestrator exec
    from ....services.orchestration import get_orchestrator

    user_id = context["user_id"]
    project_id = context["project_id"]
    project_slug = context.get("project_slug", "")
    container_name = context.get("container_name")

    try:
        orchestrator = get_orchestrator()

        # orchestrator.execute_command expects a raw service/directory name
        # (e.g. "next-js-15") — it builds the full container name internally.
        # When container_name is None (single-container project), resolve the
        # default service name from the running project status.
        if not container_name:
            status = await orchestrator.get_project_status(project_slug, str(project_id))
            containers = status.get("containers", {})
            # Pick the first running service, or first service if none running
            for svc_name, info in containers.items():
                if info.get("running"):
                    container_name = svc_name
                    break
            if not container_name and containers:
                container_name = next(iter(containers.keys()))
            if not container_name:
                raise RuntimeError("No containers found. Please start the project first.")

        logger.info(f"[BASH] Resolved container: {container_name}")

        # The orchestrator's execute_command expects command as a list.
        # Wrap in /bin/sh -c so the shell interprets pipes, redirects, etc.
        cmd_list = ["/bin/sh", "-c", command]

        output = await orchestrator.execute_command(
            user_id=user_id,
            project_id=UUID(str(project_id)) if not isinstance(project_id, UUID) else project_id,
            container_name=container_name,
            command=cmd_list,
            timeout=timeout,
        )

        # Strip ANSI control codes from output
        clean_output = strip_ansi_codes(output) if output else ""

        logger.info(f"[BASH] Command completed, output_length={len(clean_output)}")

        return success_output(
            message=f"Executed '{command}'",
            output=clean_output,
            details={
                "command": command,
                "exit_code": 0,
            },
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[BASH] Command failed: {error_msg}")

        # Distinguish timeout from other errors
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            return error_output(
                message=f"Command timed out after {timeout}s: {command}",
                suggestion="Try a shorter command or increase the timeout parameter",
                details={"command": command, "timeout": timeout, "error": error_msg},
            )

        return error_output(
            message=f"Command execution failed: {error_msg}",
            suggestion="Check your command syntax and ensure the dev container is running",
            details={"command": command, "error": error_msg},
        )


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
