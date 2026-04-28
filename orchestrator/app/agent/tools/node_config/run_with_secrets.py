"""``run_with_secrets`` — scoped shell exec with named encrypted secrets.

Loads a subset of a container's ``encrypted_secrets``, decrypts them, and
runs a shell command with those values injected as env vars. The captured
stdout/stderr is scrubbed of any secret substring via ``_secret_scrubber``
before being returned to the agent.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from ....models import Container
from ....services.deployment_encryption import (
    DeploymentEncryptionError,
    get_deployment_encryption_service,
)
from .._secret_scrubber import scrub_text
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def _run_with_env(
    context: dict[str, Any],
    *,
    command: str,
    env: dict[str, str],
    cwd: str | None,
) -> tuple[str, int]:
    """Execute *command* inside the project's execution path with *env* injected.

    We reuse the normal bash executor and prepend shell-quoted ``export`` lines.
    For safety, the exported values are never emitted to the agent — the
    subsequent scrub pass will hide them if the command accidentally echoes.
    """
    import shlex

    exports = " && ".join(
        f"export {k}={shlex.quote(v)}" for k, v in env.items()
    )
    if cwd:
        full_cmd = f"cd {shlex.quote(cwd)} && {exports} && {command}" if exports else (
            f"cd {shlex.quote(cwd)} && {command}"
        )
    else:
        full_cmd = f"{exports} && {command}" if exports else command

    # Delegate to the existing bash_exec executor so K8s/docker/local paths all work.
    from ..shell_ops.bash import bash_exec_tool

    try:
        result = await bash_exec_tool({"command": full_cmd}, context)
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("[run_with_secrets] bash_exec failed")
        return f"Command execution failed: {e}", 1

    # Normalize output text
    if isinstance(result, dict):
        output = result.get("output") or result.get("message") or ""
        exit_code = 0 if result.get("success") else 1
        details = result.get("details") or {}
        ec = details.get("exit_code")
        if isinstance(ec, int):
            exit_code = ec
        return str(output), int(exit_code)
    return str(result), 0


async def run_with_secrets_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    command = params.get("command")
    container_id = params.get("container_id")
    secret_keys = params.get("secret_keys") or []
    cwd = params.get("cwd")

    if not command or not container_id:
        return error_output(message="command and container_id are required")
    if not isinstance(secret_keys, list):
        return error_output(message="secret_keys must be a list of strings")

    db = context.get("db")
    project_id = context.get("project_id")
    if db is None or project_id is None:
        return error_output(message="Tool missing db/project_id context")

    try:
        container_uuid = UUID(str(container_id))
    except Exception:
        return error_output(message=f"Invalid container_id '{container_id}'")

    container = await db.get(Container, container_uuid)
    if container is None or container.project_id != project_id:
        return error_output(
            message=f"Container {container_id} not found in this project"
        )

    encrypted = container.encrypted_secrets or {}
    enc_service = get_deployment_encryption_service()

    env: dict[str, str] = {}
    missing: list[str] = []
    for key in secret_keys:
        if key not in encrypted:
            missing.append(key)
            continue
        try:
            env[key] = enc_service.decrypt(encrypted[key])
        except DeploymentEncryptionError:
            missing.append(key)

    if missing:
        return error_output(
            message=f"Unknown or undecryptable secret keys: {missing}",
            suggestion=(
                "Use request_node_config to set these secrets before invoking "
                "run_with_secrets."
            ),
        )

    output, exit_code = await _run_with_env(
        context, command=command, env=env, cwd=cwd
    )

    # Scrub any secret substring from captured output BEFORE returning to agent.
    scrub_map = {v: k for k, v in env.items() if v and len(v) >= 6}
    safe_output = scrub_text(output, scrub_map)

    if exit_code != 0:
        return error_output(
            message=f"Command failed (exit code {exit_code})",
            details={"exit_code": exit_code, "output": safe_output, "command": command},
        )
    return success_output(
        message=f"Executed '{command}' with {len(env)} secret(s) injected",
        output=safe_output,
        details={"exit_code": exit_code, "injected_keys": list(env.keys())},
    )


def register_run_with_secrets_tool(registry) -> None:
    registry.register(
        Tool(
            name="run_with_secrets",
            description=(
                "Run a shell command with named encrypted secrets from a Container "
                "injected as env vars. The agent references secrets by KEY ONLY; "
                "values are never returned. Any substring match of a secret in "
                "stdout/stderr is replaced with «secret:KEY» before you see it."
            ),
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run (bash -c).",
                    },
                    "container_id": {
                        "type": "string",
                        "description": "UUID of the Container holding the secrets.",
                    },
                    "secret_keys": {
                        "type": "array",
                        "description": "List of env-var key names to inject.",
                        "items": {"type": "string"},
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory (inside the project).",
                    },
                },
                "required": ["command", "container_id", "secret_keys"],
            },
            executor=run_with_secrets_executor,
            # Command + key names in, exit_code+scrubbed_output dict out — JSON-clean.
            state_serializable=True,
            # Spawns a subprocess but waits to completion before returning;
            # no in-tool persistent handle (unlike bash_exec is_background).
            holds_external_state=False,
            examples=[
                '{"tool_name": "run_with_secrets", "parameters": {"command": "npx supabase migration up", "container_id": "…", "secret_keys": ["SUPABASE_SERVICE_KEY"]}}',
            ],
        )
    )
    logger.info("Registered node_config tool: run_with_secrets")
