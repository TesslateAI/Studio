"""
Bash Convenience Tool

Executes shell commands for the agent. Behavior depends on deployment mode:

- **Local mode**: spawns the command under a PTY (so curses/TUI binaries,
  color output, and interactive tools behave naturally). Supports
  ``yield_time_ms`` soft yield, ``idle_timeout_ms`` idle-kill,
  ``is_background=True`` fire-and-forget, and output-token truncation.
- **Docker mode**: delegates to the orchestrator's ``execute_command``
  (asyncio subprocess into the container).
- **Kubernetes mode**: Tier 1 (ephemeral) or Tier 2 (environment) exec
  into the user's dev pod, unchanged from the pre-upgrade implementation.
"""

import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from ..output_formatter import error_output, strip_ansi_codes, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

# One token is roughly four bytes of English text; the tool truncates the
# accumulated PTY output at ``max_output_tokens * _BYTES_PER_TOKEN`` bytes.
_BYTES_PER_TOKEN = 4
_TRUNCATION_MARKER = "\n[truncated]\n"


def _has_volume_hints(context: dict[str, Any]) -> bool:
    """Check if the context includes volume routing hints (required for K8s execution)."""
    return context.get("volume_id") is not None


async def _run_ephemeral(context: dict[str, Any], command: str, timeout: int) -> dict[str, Any]:
    """Execute a command via ComputeManager ephemeral pod (Tier 1)."""
    from ....database import AsyncSessionLocal
    from ....models import Project
    from ....services.compute_manager import ComputeQuotaExceeded, get_compute_manager

    volume_id = context["volume_id"]
    project_id = context["project_id"]

    compute = get_compute_manager()

    # Resolve the live node from the Hub (~5ms) so the pod lands on the
    # volume's node. Never use stale DB cache — the Hub is truth.
    from ....services.volume_manager import get_volume_manager

    vm = get_volume_manager()
    node_name = await vm.get_volume_node(volume_id)

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


def _resolve_run_id(context: dict[str, Any]) -> str | None:
    """Extract the invocation identifier from the tool-call context."""
    for key in ("run_id", "chat_id", "task_id", "message_id"):
        value = context.get(key)
        if value:
            return str(value)
    return None


def _truncate_output(text: str, max_output_tokens: int) -> tuple[str, bool]:
    """Truncate ``text`` to at most ``max_output_tokens * 4`` bytes."""
    if max_output_tokens <= 0:
        return text, False
    budget = max_output_tokens * _BYTES_PER_TOKEN
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= budget:
        return text, False
    # Keep the tail — most shell tools emit the interesting bit last.
    tail = encoded[-budget:]
    try:
        decoded = tail.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        decoded = tail.decode("latin-1", errors="replace")
    return _TRUNCATION_MARKER + decoded, True


async def _run_local_pty(
    context: dict[str, Any],
    command: str,
    timeout: int,
    yield_time_ms: int,
    max_output_tokens: int,
    is_background: bool,
    idle_timeout_ms: int,
) -> dict[str, Any]:
    """Execute ``command`` in local mode under a dedicated PTY session."""
    import os
    import signal
    import time

    from ....services.orchestration.local import PTY_SESSIONS

    run_id = _resolve_run_id(context)
    cwd = context.get("cwd") or os.environ.get("PROJECT_ROOT") or os.getcwd()

    try:
        session_id = PTY_SESSIONS.create(command, cwd=cwd, run_id=run_id)
    except FileNotFoundError as exc:
        return error_output(
            message=f"Failed to spawn PTY session: {exc}",
            suggestion="Verify the shell is installed and accessible",
            details={"command": command, "tier": "local"},
        )
    except OSError as exc:
        return error_output(
            message=f"Failed to spawn PTY session: {exc}",
            suggestion="Check that /dev/ptmx is available and writable",
            details={"command": command, "tier": "local"},
        )

    snapshot = PTY_SESSIONS.status(session_id)

    if is_background:
        logger.info(
            "[BASH-LOCAL] Background PTY session %s spawned pid=%s cmd=%r",
            session_id,
            snapshot.get("pid"),
            command,
        )
        return success_output(
            message=f"Started background PTY session {session_id}",
            session_id=session_id,
            details={
                "command": command,
                "pid": snapshot.get("pid"),
                "status": "running",
                "tier": "local",
                "is_background": True,
            },
        )

    # Foreground: drain until exit / timeout / yield / idle.
    hard_deadline_ms = max(1, int(timeout)) * 1000
    yield_ms = max(0, int(yield_time_ms))
    max_duration_ms = hard_deadline_ms if yield_ms == 0 else min(hard_deadline_ms, yield_ms)

    output_bytes = bytearray()
    start = time.monotonic()
    truncated = False

    max_bytes_budget = max_output_tokens * _BYTES_PER_TOKEN if max_output_tokens > 0 else None

    try:
        while True:
            remaining_ms = hard_deadline_ms - int((time.monotonic() - start) * 1000)
            if remaining_ms <= 0:
                # Hard timeout — kill the process group.
                logger.warning(
                    "[BASH-LOCAL] Command timed out after %ss: %s",
                    timeout,
                    command[:100],
                )
                entry_pgid = None
                try:
                    entry_pgid = PTY_SESSIONS._sessions[session_id].get("pgid")  # noqa: SLF001
                except KeyError:
                    entry_pgid = None
                if entry_pgid:
                    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                        os.killpg(entry_pgid, signal.SIGTERM)
                    import asyncio as _asyncio

                    await _asyncio.sleep(2.0)
                    try:
                        if PTY_SESSIONS._sessions[session_id]["pty"].isalive():  # noqa: SLF001
                            os.killpg(entry_pgid, signal.SIGKILL)
                    except (KeyError, ProcessLookupError, PermissionError, OSError):
                        pass

                # Capture whatever is left, then close.
                tail = PTY_SESSIONS.read(session_id, max_bytes=65536)
                if tail:
                    output_bytes.extend(tail)
                PTY_SESSIONS.close(session_id)

                text = output_bytes.decode("utf-8", errors="replace")
                clean = strip_ansi_codes(text)
                clean, trunc_now = _truncate_output(clean, max_output_tokens)
                return error_output(
                    message=f"Command timed out after {timeout}s: {command}",
                    suggestion=(
                        "Increase the timeout, use is_background=True, or split the "
                        "command into smaller steps"
                    ),
                    details={
                        "command": command,
                        "timeout": timeout,
                        "output": clean,
                        "truncated": truncated or trunc_now,
                        "exit_code": 124,
                        "session_id": session_id,
                        "tier": "local",
                    },
                )

            drain_budget_ms = min(max_duration_ms, remaining_ms)
            chunk = await PTY_SESSIONS.drain(
                session_id=session_id,
                max_duration_ms=drain_budget_ms,
                idle_timeout_ms=idle_timeout_ms,
                max_bytes=max_bytes_budget,
                wait_for_exit=True,
            )
            if chunk:
                output_bytes.extend(chunk)

            status_snapshot = PTY_SESSIONS.status(session_id)
            if status_snapshot["status"] == "exited":
                # Final flush.
                tail = PTY_SESSIONS.read(session_id, max_bytes=65536)
                if tail:
                    output_bytes.extend(tail)
                exit_code = status_snapshot.get("exit_code")
                PTY_SESSIONS.close(session_id)

                text = output_bytes.decode("utf-8", errors="replace")
                clean = strip_ansi_codes(text)
                clean, trunc_now = _truncate_output(clean, max_output_tokens)
                truncated = truncated or trunc_now

                logger.info(
                    "[BASH-LOCAL] Command completed exit=%s output_length=%d",
                    exit_code,
                    len(clean),
                )

                details = {
                    "command": command,
                    "exit_code": exit_code if exit_code is not None else 0,
                    "output": clean,
                    "status": "exited",
                    "truncated": truncated,
                    "session_id": session_id,
                    "tier": "local",
                }

                if exit_code not in (None, 0):
                    return error_output(
                        message=f"Command failed (exit code {exit_code}): {command}",
                        suggestion="Check the output for errors",
                        details=details,
                    )
                return success_output(
                    message=f"Executed '{command}'",
                    output=clean,
                    details=details,
                )

            if max_bytes_budget is not None and len(output_bytes) >= max_bytes_budget:
                # Budget hit — mark truncated, kill the process, return early.
                truncated = True
                entry_pgid = None
                try:
                    entry_pgid = PTY_SESSIONS._sessions[session_id].get("pgid")  # noqa: SLF001
                except KeyError:
                    entry_pgid = None
                if entry_pgid:
                    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                        os.killpg(entry_pgid, signal.SIGTERM)
                PTY_SESSIONS.close(session_id)

                text = output_bytes.decode("utf-8", errors="replace")
                clean = strip_ansi_codes(text)
                clean, _ = _truncate_output(clean, max_output_tokens)
                return success_output(
                    message=f"Executed '{command}' (output truncated at budget)",
                    output=clean,
                    details={
                        "command": command,
                        "exit_code": None,
                        "status": "truncated",
                        "truncated": True,
                        "session_id": session_id,
                        "tier": "local",
                    },
                )

            # If the yield window has elapsed without an exit, return a
            # partial snapshot so the agent can decide whether to continue.
            if yield_ms > 0 and int((time.monotonic() - start) * 1000) >= yield_ms:
                text = output_bytes.decode("utf-8", errors="replace")
                clean = strip_ansi_codes(text)
                clean, trunc_now = _truncate_output(clean, max_output_tokens)
                truncated = truncated or trunc_now
                logger.info(
                    "[BASH-LOCAL] Yield after %dms, session %s still running",
                    yield_ms,
                    session_id,
                )
                return success_output(
                    message=f"Yielded after {yield_ms}ms; session {session_id} still running",
                    output=clean,
                    details={
                        "command": command,
                        "exit_code": None,
                        "status": "running",
                        "truncated": truncated,
                        "session_id": session_id,
                        "tier": "local",
                    },
                )
    except Exception as exc:
        logger.error("[BASH-LOCAL] Execution error for %r: %s", command, exc, exc_info=True)
        with contextlib.suppress(Exception):
            PTY_SESSIONS.close(session_id)
        return error_output(
            message=f"Command execution failed: {exc}",
            suggestion="Inspect the traceback and retry",
            details={"command": command, "error": str(exc), "tier": "local"},
        )


async def bash_exec_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a single command.

    In **local** mode, the command runs under a dedicated PTY session and
    supports background/yield/idle/truncation semantics. In **docker** and
    **kubernetes** modes the call is delegated to the matching orchestrator
    path unchanged.

    Args:
        params: {
            command: str,
            timeout: int = 120,
            yield_time_ms: int = 10000,
            max_output_tokens: int = 16384,
            is_background: bool = False,
            idle_timeout_ms: int = 0,
        }
        context: {user_id, project_id, db, container_name?, chat_id?, run_id?, ...}
    """
    command = params.get("command")
    timeout = int(params.get("timeout", 120))
    yield_time_ms = int(params.get("yield_time_ms", 10000))
    max_output_tokens = int(params.get("max_output_tokens", 16384))
    is_background = bool(params.get("is_background", False))
    idle_timeout_ms = int(params.get("idle_timeout_ms", 0))

    if not command:
        raise ValueError("command parameter is required")

    logger.info(f"[BASH] Executing: {command[:100]}... (bg={is_background})")

    from ....config import get_settings

    settings = get_settings()
    mode = getattr(settings, "deployment_mode", None)

    # Local mode: PTY-backed execution with the upgraded feature set.
    if mode == "local":
        return await _run_local_pty(
            context=context,
            command=command,
            timeout=timeout,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
            is_background=is_background,
            idle_timeout_ms=idle_timeout_ms,
        )

    # Non-local modes do not support background spawning via this tool —
    # the caller should use shell_open / shell_exec for persistent
    # sessions in containerized deployments.
    if is_background:
        return error_output(
            message="is_background=True is only supported in local deployment mode",
            suggestion="Use shell_open + shell_exec for persistent sessions in Docker/K8s mode",
            details={"command": command},
        )

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
            description=(
                "Execute a bash/sh command and return its output. In local mode the "
                "command runs under a PTY, supports soft yielding via yield_time_ms, "
                "idle detection via idle_timeout_ms, background spawning via "
                "is_background=True, and output truncation via max_output_tokens."
            ),
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
                        "description": "Hard timeout in seconds — the process group is killed when it elapses (default: 120)",
                        "default": 120,
                    },
                    "yield_time_ms": {
                        "type": "integer",
                        "description": (
                            "Soft yield window in milliseconds. If the command is still "
                            "running after this window elapses, bash_exec returns a partial "
                            "snapshot with status=running and the session_id so the agent "
                            "can poll or send stdin. 0 disables soft yield. Default: 10000."
                        ),
                        "default": 10000,
                    },
                    "max_output_tokens": {
                        "type": "integer",
                        "description": (
                            "Approximate output budget in model tokens (4 bytes/token). "
                            "Output beyond this is truncated with a [truncated] marker. "
                            "Default: 16384."
                        ),
                        "default": 16384,
                    },
                    "is_background": {
                        "type": "boolean",
                        "description": (
                            "When true, spawn the command as a detached PTY session and "
                            "return immediately with the session_id. Use "
                            "list_background_processes and read_background_output to "
                            "inspect it later. Local mode only."
                        ),
                        "default": False,
                    },
                    "idle_timeout_ms": {
                        "type": "integer",
                        "description": (
                            "Idle output timeout in milliseconds. When >0 and no new output "
                            "arrives for this long, bash_exec yields a partial snapshot. "
                            "0 disables the idle timeout. Default: 0."
                        ),
                        "default": 0,
                    },
                },
                "required": ["command"],
            },
            executor=bash_exec_tool,
            examples=[
                '{"tool_name": "bash_exec", "parameters": {"command": "npm install"}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "ls -la", "timeout": 30}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "npm run dev", "is_background": true}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "pytest -x", "yield_time_ms": 5000, "idle_timeout_ms": 2000}}',
            ],
        )
    )

    logger.info("Registered 1 bash convenience tool")
