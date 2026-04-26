"""``request_node_config`` — agent-driven node configuration with hard pause.

Flow:
  1. Agent calls the tool with ``node_name`` + ``preset`` (± overrides).
  2. Tool creates (or loads, in edit mode) a Container row.
  3. Publishes ``architecture_node_added`` so the canvas updates live.
  4. Publishes ``user_input_required`` carrying the form schema. Secret
     fields NEVER ship with their values — edit-mode initial_values mark
     populated secrets with the sentinel ``"__SET__"`` instead.
  5. Awaits the user's submit / cancel response via Redis pub/sub.
  6. Merges + encrypts via ``apply_node_config``, writes AuditLog, emits
     ``node_config_resumed`` / ``node_config_cancelled`` / ``secret_rotated``.
  7. Returns a dict to the agent with KEY NAMES only — no secret values.

A heartbeat is emitted every 30s while awaiting input so the UI can show the
agent is still alive (and operators can distinguish a waiting task from a
crashed one).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ....config import get_settings
from ....models import Container, Project
from ....services.node_config_presets import FormSchema, resolve_schema
from ....services.pubsub import get_pubsub
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30


async def _publish(task_id: str | None, event: dict) -> None:
    if not task_id:
        return
    pubsub = get_pubsub()
    if pubsub is None:
        return
    try:
        await pubsub.publish_agent_event(task_id, event)
    except Exception:
        logger.exception("[request_node_config] failed to publish event")


async def _heartbeat_loop(task_id: str | None, input_id: str) -> None:
    """Emit a heartbeat event every 30s so the UI/worker can show liveness."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await _publish(
                task_id,
                {
                    "type": "agent_heartbeat",
                    "data": {
                        "reason": "waiting_for_user_input",
                        "input_id": input_id,
                    },
                },
            )
    except asyncio.CancelledError:
        return


async def _await_with_heartbeat(task_id: str | None, input_id: str, timeout: int):
    from ..approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()
    hb_task = asyncio.create_task(_heartbeat_loop(task_id, input_id))
    try:
        return await manager.await_input(input_id, timeout=timeout)
    finally:
        hb_task.cancel()
        with _suppress_cancel():
            await hb_task


class _suppress_cancel:
    """Small context manager: swallow a single CancelledError on exit."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError

    # Support `async with`
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError


async def _auto_position(db, project_id: UUID) -> tuple[float, float]:
    result = await db.execute(
        select(Container.position_x, Container.position_y).where(
            Container.project_id == project_id
        )
    )
    xs = [r[0] or 0 for r in result.all()]
    if not xs:
        return 200.0, 200.0
    return 200.0 + (len(xs) * 240.0), 200.0


async def _load_or_create_container(
    db,
    *,
    project_id: UUID,
    mode: str,
    node_name: str,
    preset: str,
    deployment_mode: str,
    container_id: str | None,
    position: dict[str, Any] | None,
) -> Container:
    if mode == "edit":
        if not container_id:
            raise ValueError("container_id is required for mode='edit'")
        container = await db.get(Container, UUID(container_id))
        if container is None or container.project_id != project_id:
            raise ValueError(f"Container {container_id} not found in project")
        return container

    # Create path
    pos_x = float((position or {}).get("x") or 0) if position else None
    pos_y = float((position or {}).get("y") or 0) if position else None
    if pos_x is None or pos_x == 0 or pos_y is None or pos_y == 0:
        auto_x, auto_y = await _auto_position(db, project_id)
        pos_x = pos_x or auto_x
        pos_y = pos_y or auto_y

    project = await db.get(Project, project_id)
    slug = getattr(project, "slug", "proj") if project else "proj"

    container = Container(
        project_id=project_id,
        name=node_name,
        directory=".",
        container_name=f"{slug}-{node_name}",
        container_type="service" if deployment_mode == "external" else "base",
        service_slug=preset if preset != "external_generic" else None,
        deployment_mode=deployment_mode,
        position_x=pos_x,
        position_y=pos_y,
        environment_vars={},
        encrypted_secrets=None,
        status="stopped" if deployment_mode == "container" else "connected",
    )
    db.add(container)
    await db.flush()
    await db.refresh(container)
    return container


def _build_initial_values_from_schema(
    container: Container, schema: FormSchema
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    env_vars = container.environment_vars or {}
    encrypted = container.encrypted_secrets or {}
    for field in schema.fields:
        if field.is_secret:
            if field.key in encrypted:
                values[field.key] = "__SET__"
        elif field.key in env_vars:
            values[field.key] = env_vars[field.key]
    return values


async def _write_audit(
    db,
    *,
    project: Project,
    user_id: UUID,
    container_id: UUID,
    summary: dict[str, list[str]],
    created: bool,
    preset: str,
    mode: str,
) -> None:
    from ....services.audit_service import log_event

    team_id = getattr(project, "team_id", None)
    if not team_id:
        return
    await log_event(
        db=db,
        team_id=team_id,
        user_id=user_id,
        action="node_config_updated",
        resource_type="container",
        resource_id=container_id,
        project_id=project.id,
        details={
            **summary,
            "created": created,
            "preset": preset,
            "mode": mode,
            "source": "agent_tool",
        },
    )


async def request_node_config_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Executor — see module docstring for flow."""
    from ....routers.node_config import apply_node_config
    from ...tools.approval_manager import get_pending_input_manager
    from ...tools.output_formatter import error_output, success_output

    node_name: str = params["node_name"]
    preset_key: str = params.get("preset") or "external_generic"
    overrides = params.get("field_overrides") or None
    mode: str = params.get("mode") or "create"
    container_id = params.get("container_id")
    position = params.get("position")

    if mode not in ("create", "edit"):
        return error_output(message=f"Invalid mode '{mode}' (must be create|edit)")
    if mode == "edit" and not container_id:
        return error_output(message="container_id is required when mode='edit'")

    db = context.get("db")
    project_id_raw = context.get("project_id")
    task_id = context.get("task_id")
    chat_id = context.get("chat_id") or context.get("session_id") or ""
    user_id_raw = context.get("user_id")
    if not db or not project_id_raw or not user_id_raw:
        return error_output(message="Tool missing db/project_id/user_id context")
    project_id = (
        project_id_raw if isinstance(project_id_raw, UUID) else UUID(str(project_id_raw))
    )
    user_id = user_id_raw if isinstance(user_id_raw, UUID) else UUID(str(user_id_raw))

    # Resolve schema up-front so we can fail fast on unknown preset.
    try:
        schema = resolve_schema(preset_key, overrides)
    except KeyError as e:
        return error_output(message=str(e))
    except ValueError as e:
        return error_output(message=f"Bad override: {e}")

    deployment_mode = schema.deployment_mode

    # 1. Create or load container.
    try:
        container = await _load_or_create_container(
            db,
            project_id=project_id,
            mode=mode,
            node_name=node_name,
            preset=preset_key,
            deployment_mode=deployment_mode,
            container_id=container_id,
            position=position,
        )
    except ValueError as e:
        return error_output(message=str(e))
    await db.commit()

    created = mode == "create"
    if created:
        await _publish(
            task_id,
            {
                "type": "architecture_node_added",
                "data": {
                    "container_id": str(container.id),
                    "container_name": container.name,
                    "deployment_mode": container.deployment_mode,
                    "position_x": container.position_x,
                    "position_y": container.position_y,
                    "preset": preset_key,
                },
            },
        )

    # 2. Pending input.
    input_id = str(uuid4())
    settings = get_settings()
    timeout = getattr(settings, "node_config_input_timeout_seconds", 1800) or 1800

    manager = get_pending_input_manager()
    await manager.create_input_request(
        input_id=input_id,
        project_id=str(project_id),
        chat_id=str(chat_id),
        container_id=str(container.id),
        schema_json=schema.to_dict(),
        mode=mode,
        ttl=timeout,
    )

    initial_values = _build_initial_values_from_schema(container, schema)
    await _publish(
        task_id,
        {
            "type": "user_input_required",
            "data": {
                "input_id": input_id,
                "container_id": str(container.id),
                "container_name": container.name,
                "preset": preset_key,
                "mode": mode,
                "schema": schema.to_dict(),
                "initial_values": initial_values,
            },
        },
    )

    # 3. Wait.
    response = await _await_with_heartbeat(task_id, input_id, timeout=int(timeout))

    if response is None or response == "__cancelled__":
        # Cancelled or timed out.
        await _publish(
            task_id,
            {
                "type": "node_config_cancelled",
                "data": {
                    "input_id": input_id,
                    "container_id": str(container.id),
                    "reason": "timeout" if response is None else "user_cancelled",
                },
            },
        )
        return success_output(
            message=(
                "User cancelled node configuration"
                if response == "__cancelled__"
                else "Node configuration timed out"
            ),
            cancelled=True,
            timed_out=response is None,
            container_id=str(container.id),
            node_name=container.name,
        )

    if not isinstance(response, dict):
        return error_output(
            message=f"Unexpected response shape for {input_id}: {type(response).__name__}"
        )

    # 4. Apply values.
    project = await db.get(Project, project_id)
    summary = apply_node_config(container, response, schema)
    await _write_audit(
        db,
        project=project,
        user_id=user_id,
        container_id=container.id,
        summary=summary,
        created=created,
        preset=preset_key,
        mode=mode,
    )
    await db.commit()

    # 5. Emit resumed + rotation events.
    await _publish(
        task_id,
        {
            "type": "node_config_resumed",
            "data": {
                "input_id": input_id,
                "container_id": str(container.id),
                "updated_keys": summary["updated_keys"],
                "rotated_secrets": summary["rotated_secrets"],
                "cleared_secrets": summary["cleared_secrets"],
                "created": created,
            },
        },
    )
    if summary["rotated_secrets"] or summary["cleared_secrets"]:
        await _publish(
            task_id,
            {
                "type": "secret_rotated",
                "data": {
                    "container_id": str(container.id),
                    "keys": summary["rotated_secrets"] + summary["cleared_secrets"],
                },
            },
        )

    # 6. Build agent-visible result — NO secret values.
    configured_keys = sorted(
        (container.environment_vars or {}).keys()
        | (container.encrypted_secrets or {}).keys()
    )
    secret_keys = sorted((container.encrypted_secrets or {}).keys())
    non_secret_values = dict(container.environment_vars or {})

    return success_output(
        message=(
            f"Configured node '{container.name}' — {len(summary['updated_keys'])} key(s) updated"
            if not created
            else f"Created and configured node '{container.name}'"
        ),
        container_id=str(container.id),
        node_name=container.name,
        configured_keys=configured_keys,
        secret_keys=secret_keys,
        non_secret_values=non_secret_values,
        updated_keys=summary["updated_keys"],
        rotated_secrets=summary["rotated_secrets"],
        cleared_secrets=summary["cleared_secrets"],
        created=created,
    )


def register_node_config_tool(registry) -> None:
    registry.register(
        Tool(
            name="request_node_config",
            description=(
                "Create (or edit) a Container node on the Architecture canvas and "
                "pause until the user fills in its configuration via the dock tab. "
                "Use for external services (Supabase, Postgres, Stripe, REST APIs) "
                "or any custom node that needs user-provided values. The tool returns "
                "only key names and non-secret values — secret values are stored "
                "encrypted and never exposed to the agent."
            ),
            category=ToolCategory.PROJECT,
            parameters={
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "Display name for the node (e.g. 'supabase').",
                    },
                    "preset": {
                        "type": "string",
                        "description": (
                            "Preset key: supabase | postgres | stripe | rest_api | "
                            "external_generic. Use external_generic with "
                            "field_overrides for a bespoke node."
                        ),
                        "default": "external_generic",
                    },
                    "field_overrides": {
                        "type": "array",
                        "description": (
                            "Optional list of field schemas to merge onto the preset. "
                            "Each item: {key, label, type, required?, is_secret?, "
                            "placeholder?, help?, options?}."
                        ),
                        "items": {"type": "object"},
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["create", "edit"],
                        "default": "create",
                    },
                    "container_id": {
                        "type": "string",
                        "description": "Required when mode='edit'.",
                    },
                    "position": {
                        "type": "object",
                        "description": "Optional {x, y} placement on the canvas.",
                    },
                },
                "required": ["node_name"],
            },
            executor=request_node_config_executor,
            # Node spec in, non-secret config map dict out — JSON-clean.
            state_serializable=True,
            # Pauses on a DB-backed pending-input row; the wait state lives
            # in the approval/HITL surface, not in this tool. Phase 2 HITL
            # may treat this specially but the tool itself is checkpointable.
            holds_external_state=False,
            examples=[
                '{"tool_name": "request_node_config", "parameters": {"node_name": "supabase", "preset": "supabase"}}',
                '{"tool_name": "request_node_config", "parameters": {"node_name": "payments", "preset": "rest_api", "field_overrides": [{"key": "PAYMENTS_API_KEY", "label": "Payments API Key", "type": "secret", "is_secret": true, "required": true}]}}',
            ],
        )
    )
    logger.info("Registered node_config tool: request_node_config")
