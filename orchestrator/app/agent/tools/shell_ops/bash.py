"""
Bash Convenience Tool

Executes shell commands for the agent. Behavior depends on deployment mode:

- **Local mode**: spawns the command under a PTY (so curses/TUI binaries,
  color output, and interactive tools behave naturally). Supports
  ``yield_time_ms`` soft yield, ``idle_timeout_ms`` idle-kill,
  ``is_background=True`` fire-and-forget, and output-token truncation.
- **Docker mode**: delegates to the orchestrator's ``execute_command``
  (asyncio subprocess into the container).
- **Kubernetes mode**: routes to Tier 1 (ephemeral one-shot pod) or
  Tier 2 (running project dev container) based on the agent-supplied
  ``tier`` param or the project's current ``compute_tier``. When
  Tier 2 is requested but not running, a structured error points the
  agent at ``project_start`` — there is no auto-wake.

Required context keys (Kubernetes mode):

    volume_id           — Project.volume_id, required for pod scheduling
    cache_node          — Project.cache_node (hint; Hub is source of truth)
    compute_tier        — Project.compute_tier, used for ``tier="auto"``
    active_compute_pod  — Project.active_compute_pod, agent visibility
    environment_status  — Project.environment_status, agent visibility
    containers          — list of {name,status,ready,is_primary,container_type}
    container_name      — default target container (overridable by param)

Populated today by ``routers/chat.py`` (3 sites) and ``worker.py`` via
``services/agent_context.build_tier_snapshot``. See
``docs/orchestrator/agent/tools/compute-tiers.md`` for the full contract.
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


async def _audit_tier_override(
    context: dict[str, Any],
    requested_tier: str,
    actual_tier: str,
    command: str,
) -> None:
    """Write an AuditLog row when the agent picks a tier that differs from
    the project's current ``compute_tier``. Non-blocking — never raises.

    Emits action=``agent.exec.tier_override`` so prod telemetry can see
    when agents are bypassing the implicit routing.
    """
    try:
        from ....database import AsyncSessionLocal
        from ....models import Project
        from ....services.audit_service import log_event

        project_id = context.get("project_id")
        user_id = context.get("user_id")
        if not project_id or not user_id:
            return

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project is None:
                return
            await log_event(
                db=db,
                team_id=project.team_id,
                user_id=user_id,
                action="agent.exec.tier_override",
                resource_type="project",
                resource_id=project_id,
                project_id=project_id,
                details={
                    "requested_tier": requested_tier,
                    "actual_tier": actual_tier,
                    "command_preview": command[:200],
                    "task_id": str(context.get("task_id")) if context.get("task_id") else None,
                },
            )
            await db.commit()
    except Exception:
        logger.exception("[BASH] Failed to audit tier override (non-blocking)")


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


async def _find_dev_pod(
    context: dict[str, Any], container_override: str | None = None
) -> tuple[Any | None, dict[str, Any] | None]:
    """Find the running dev container pod for a project.

    When *container_override* is provided it overrides the context-level
    ``container_name`` default so the agent can target a specific service
    container in a multi-container project via the bash_exec ``container``
    param. Returns (pod, None) on success or (None, error_dict) on failure.
    """
    import asyncio

    from kubernetes.client.rest import ApiException as K8sApiException

    project_id = context["project_id"]
    namespace = f"proj-{project_id}"
    container_name = container_override or context.get("container_name")

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
                message="Tier 2 environment is not running",
                suggestion=(
                    "Call project_start to start the environment, then retry "
                    "bash_exec. project_start blocks until pods are Ready "
                    "(~5s warm, ~60s cold)."
                ),
                details={
                    "tier": "environment",
                    "next_tool": "project_start",
                    "namespace": namespace,
                    "reason": "namespace_not_found",
                },
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
            message="Tier 2 environment is not running",
            suggestion=(
                "Call project_start to start the environment, then retry "
                "bash_exec. project_start blocks until pods are Ready "
                "(~5s warm, ~60s cold). To run commands without waking the "
                "environment, use tier='ephemeral'."
            ),
            details={
                "tier": "environment",
                "next_tool": "project_start",
                "namespace": namespace,
                "reason": "no_running_dev_pod",
                "requested_container": container_name,
            },
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


async def _run_environment(
    context: dict[str, Any],
    command: str,
    timeout: int,
    container_override: str | None = None,
) -> dict[str, Any]:
    """Execute a command in a running Tier 2 dev container.

    Tries tsinit WebSocket first (structured exit codes, clean stdout/stderr
    separation). Falls back to kubectl exec if tsinit is not reachable. When
    *container_override* is set, the dev pod for that specific named service
    container is targeted.
    """
    pod, err = await _find_dev_pod(context, container_override=container_override)
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


def _resolve_cwd(context: dict[str, Any], params_cwd: str | None) -> str:
    """Resolve a working directory for the spawned process.

    ``params_cwd`` — when provided — is treated as relative to the
    project root (``context["cwd"]`` or ``$PROJECT_ROOT`` or the current
    process ``cwd``). Absolute paths are silently joined under the root.
    """
    import os

    base = context.get("cwd") or os.environ.get("PROJECT_ROOT") or os.getcwd()
    if not params_cwd:
        return base
    candidate = os.path.join(base, params_cwd) if not os.path.isabs(params_cwd) else params_cwd
    return candidate


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
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute ``command`` in local mode under a dedicated PTY session."""
    import os
    import signal
    import time

    from ....services.orchestration.local import PTY_SESSIONS

    run_id = _resolve_run_id(context)
    resolved_cwd = _resolve_cwd(context, cwd)

    try:
        session_id = PTY_SESSIONS.create(
            command,
            cwd=resolved_cwd,
            env=env,
            run_id=run_id,
        )
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
            cwd: str | None,
            timeout: int = 120,
            timeout_ms: int | None,
            yield_time_ms: int = 10000,
            max_output_tokens: int = 16384,
            env: dict[str, str] | None,
            is_background: bool = False,
            idle_timeout_ms: int = 0,
        }
        context: {user_id, project_id, db, container_name?, chat_id?, run_id?, ...}
    """
    command = params.get("command")
    # Accept either ``timeout`` (seconds) or ``timeout_ms`` (milliseconds).
    if "timeout_ms" in params and params["timeout_ms"] is not None:
        timeout = max(1, int(params["timeout_ms"]) // 1000)
    else:
        timeout = int(params.get("timeout", 120))
    yield_time_ms = int(params.get("yield_time_ms", 10000))
    max_output_tokens = int(params.get("max_output_tokens", 16384))
    is_background = bool(params.get("is_background", False))
    idle_timeout_ms = int(params.get("idle_timeout_ms", 0))
    tier_param = (params.get("tier") or "auto").lower()
    container_param = params.get("container")
    cwd = params.get("cwd")
    env = params.get("env")
    if env is not None and not isinstance(env, dict):
        raise ValueError("env must be a mapping of str -> str")

    if tier_param not in ("auto", "ephemeral", "environment"):
        return error_output(
            message=f"Invalid tier '{tier_param}'",
            suggestion="tier must be one of: auto, ephemeral, environment",
            details={"command": command},
        )

    if not command:
        raise ValueError("command parameter is required")

    logger.info(
        "[BASH] Executing: %s... (bg=%s, tier=%s, container=%s)",
        command[:100],
        is_background,
        tier_param,
        container_param,
    )

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
            cwd=cwd,
            env=env,
        )

    # Desktop mode: PTY execution against the local project directory.
    if mode == "desktop":
        import uuid as _uuid

        from ....database import AsyncSessionLocal
        from ....models import Project
        from ....services.project_fs import get_project_fs_path

        project_id = context.get("project_id")
        cwd = None
        if project_id:
            try:
                _pid = (
                    _uuid.UUID(str(project_id))
                    if not isinstance(project_id, _uuid.UUID)
                    else project_id
                )
                async with AsyncSessionLocal() as _db:
                    _proj = await _db.get(Project, _pid)
                    if _proj is not None:
                        _path = get_project_fs_path(_proj)
                        if _path is not None and _path.exists():
                            cwd = str(_path)
            except Exception:
                pass

        desktop_context = {**context, "cwd": cwd} if cwd else context
        return await _run_local_pty(
            context=desktop_context,
            command=command,
            timeout=timeout,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
            is_background=is_background,
            idle_timeout_ms=idle_timeout_ms,
        )

    # Docker/K8s modes do not support background spawning via this tool.
    if is_background:
        return error_output(
            message="is_background=True is only supported in local/desktop deployment mode",
            suggestion="Use shell_open + shell_exec for persistent sessions in Docker/K8s mode",
            details={"command": command},
        )

    if settings.is_docker_mode:
        # Docker mode has no tiering — tier / container params are accepted
        # for forward-compat but ignored here (all containers reachable via
        # the orchestrator's execute_command path).
        return await _run_docker(context, command, timeout)

    # K8s mode: requires volume routing hints for pod scheduling
    if not _has_volume_hints(context):
        return error_output(
            message="Missing volume routing hints — cannot execute command",
            suggestion="Ensure the project has a valid volume_id and cache_node",
            details={"command": command},
        )

    actual_tier = context.get("compute_tier")

    if tier_param == "environment":
        resolved_tier = "environment"
    elif tier_param == "ephemeral":
        resolved_tier = "ephemeral"
    else:  # auto
        resolved_tier = "environment" if actual_tier == "environment" else "ephemeral"

    # Audit tier override — when the agent explicitly chose a tier that
    # disagrees with what the project is currently in.
    if tier_param != "auto" and actual_tier and tier_param != actual_tier:
        await _audit_tier_override(
            context=context,
            requested_tier=tier_param,
            actual_tier=actual_tier,
            command=command,
        )

    if resolved_tier == "environment":
        return await _run_environment(context, command, timeout, container_override=container_param)

    # Ephemeral path ignores container_param — one-shot pods run in the
    # generic ephemeral image, not a specific service container.
    return await _run_ephemeral(context, command, timeout)


def register_bash_tools(registry):
    """Register bash convenience tools."""

    registry.register(
        Tool(
            name="bash_exec",
            description=(
                "Execute a bash/sh command and return its output. In local mode "
                "the command runs under a PTY with yield/idle/background/"
                "truncation controls. In Kubernetes mode the command is routed "
                "to one of two compute tiers: Tier 1 'ephemeral' spawns a "
                "short-lived isolated pod (fast, stateless, no services "
                "reachable); Tier 2 'environment' execs into the running "
                "project dev container (services + network reachable but "
                "requires project_start first). Use the 'tier' param to pick "
                "explicitly, or leave it 'auto' to follow the project's "
                "current compute_tier. If Tier 2 is requested but not running, "
                "the tool returns a structured error pointing at project_start."
            ),
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute (e.g., 'npm install', 'ls -la', 'cat package.json')",
                    },
                    "cwd": {
                        "type": "string",
                        "description": (
                            "Working directory relative to the project root. "
                            "Defaults to the project root itself. Local mode only."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Hard timeout in seconds — the process group is killed when it elapses (default: 120)",
                        "default": 120,
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": (
                            "Alternative hard timeout expressed in milliseconds. "
                            "When provided, overrides ``timeout``. Local mode only."
                        ),
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
                    "env": {
                        "type": "object",
                        "description": (
                            "Optional environment variable overrides applied on top of "
                            "the current process environment. Local mode only."
                        ),
                        "additionalProperties": {"type": "string"},
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
                    "tier": {
                        "type": "string",
                        "enum": ["auto", "ephemeral", "environment"],
                        "description": (
                            "K8s compute tier to execute in. 'ephemeral' (Tier 1) "
                            "spawns a short-lived pod for isolated one-shot commands "
                            "— fast to cold-start, no services reachable. "
                            "'environment' (Tier 2) execs into the running project "
                            "dev container — services and network reachable but "
                            "requires project_start first. 'auto' (default) follows "
                            "the project's current compute_tier. Ignored in local "
                            "and docker modes."
                        ),
                        "default": "auto",
                    },
                    "container": {
                        "type": "string",
                        "description": (
                            "Name of the service container to exec into (Tier 2 "
                            "environment only). Use for multi-container projects "
                            "to target e.g. 'backend' instead of the default dev "
                            "container. Ignored in ephemeral mode. Omit to use "
                            "the project's primary dev container."
                        ),
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
                '{"tool_name": "bash_exec", "parameters": {"command": "curl localhost:3000/health", "tier": "environment"}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "cat package.json", "tier": "ephemeral"}}',
                '{"tool_name": "bash_exec", "parameters": {"command": "ps aux", "tier": "environment", "container": "backend"}}',
            ],
        )
    )

    logger.info("Registered 1 bash convenience tool")
