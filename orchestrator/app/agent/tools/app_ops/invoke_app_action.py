"""invoke_app_action — call a typed action on an installed Tesslate App.

Phase 1 of the App Runtime Contract: agents can compose installed apps
without leaving chat. The agent passes ``app_instance_id`` + ``action_name``
+ ``input`` dict; the dispatcher validates against the action's declared
``input_schema``, runs the handler, validates the output against the
declared ``output_schema``, persists declared artifacts, and returns the
typed result.

Required scope: ``app.invoke``. The agent's contract may further restrict
which apps are allowed (Phase 2 enforces ``allow_apps``); Phase 1 just
runs against any installed app the caller can resolve.

Failure handling: dispatch errors are returned as a typed
``{ok: False, error, message}`` payload — the tool deliberately does NOT
re-raise. Agents handle structured error results far better than
exceptions, and a wrapped error keeps the agent loop unblocked.

Reference: /Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md
§"App actions" + §"invoke_app_action".
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def invoke_app_action_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """
    Invoke a typed action on an installed Tesslate App.

    Args:
        params: {
            app_instance_id: str  # UUID of the installed app instance
            action_name: str      # Action name as declared in the manifest
            input: dict           # Optional input payload (default: {})
        }
        context: Execution context with ``db`` (AsyncSession) and optional
            ``automation_run_id`` (used to attribute artifacts + spend).

    Returns:
        Standard tool result dict. On success the ``message`` describes the
        invocation and extra fields carry the typed dispatcher output:

            {success: True, message, ok: True, output, artifact_ids,
             spend_usd, duration_seconds}

        On dispatch failure (validation error, handler 5xx, unsupported
        kind, etc.) the dispatcher's typed error is surfaced as a clean
        result so the agent can react without an exception:

            {success: False, message, ok: False, error, suggestion}
    """
    app_instance_id_raw = params.get("app_instance_id")
    action_name = params.get("action_name")
    input_value = params.get("input") or {}

    if not app_instance_id_raw:
        return error_output(
            message="app_instance_id parameter is required",
            suggestion="Pass the UUID of the installed app instance to invoke.",
            ok=False,
        )
    if not action_name:
        return error_output(
            message="action_name parameter is required",
            suggestion="Pass the action name as declared in the app's manifest "
            "(e.g., 'summarize_pipeline').",
            ok=False,
        )
    if not isinstance(input_value, dict):
        return error_output(
            message=f"input must be a dict, got {type(input_value).__name__}",
            suggestion="Pass a JSON object — keys must match the action's "
            "declared input_schema.",
            ok=False,
        )

    db = context.get("db")
    if db is None:
        return error_output(
            message="Database session not available in execution context",
            suggestion="This is an internal error — please report it.",
            ok=False,
        )

    try:
        app_instance_id = UUID(str(app_instance_id_raw))
    except (TypeError, ValueError):
        return error_output(
            message=f"app_instance_id is not a valid UUID: {app_instance_id_raw!r}",
            suggestion="Pass the UUID string of an installed app instance.",
            ok=False,
        )

    run_id: UUID | None = None
    raw_run_id = context.get("automation_run_id")
    if raw_run_id:
        try:
            run_id = UUID(str(raw_run_id))
        except (TypeError, ValueError):
            logger.warning(
                "invoke_app_action: ignoring non-UUID automation_run_id=%r",
                raw_run_id,
            )
            run_id = None

    # Late import — keeps the apps service off the import path for sessions
    # that never invoke an app action.
    from ....services.apps.action_dispatcher import (
        ActionDispatchError,
        dispatch_app_action,
    )

    try:
        result = await dispatch_app_action(
            db,
            app_instance_id=app_instance_id,
            action_name=str(action_name),
            input=input_value,
            run_id=run_id,
            invocation_subject_id=None,  # Phase 2 wires per-caller subjects
        )
    except ActionDispatchError as exc:
        # Typed dispatcher errors (input invalid, output invalid, handler
        # not supported, etc.) — surface cleanly to the agent.
        logger.info(
            "invoke_app_action dispatch error app_instance=%s action=%s: %s",
            app_instance_id,
            action_name,
            exc,
        )
        return error_output(
            message=f"App action dispatch failed: {exc}",
            suggestion="Check the action name + input shape against the app's "
            "manifest, or inspect the app's runtime status.",
            ok=False,
            error=exc.__class__.__name__,
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — never crash the agent loop
        logger.exception(
            "invoke_app_action unexpected error app_instance=%s action=%s",
            app_instance_id,
            action_name,
        )
        return error_output(
            message=f"App action failed unexpectedly: {exc}",
            suggestion="This is likely a bug in the dispatcher or the app's "
            "handler — re-running the same call is safe to try.",
            ok=False,
            error=exc.__class__.__name__,
            error_message=str(exc),
        )

    return success_output(
        message=f"Invoked '{action_name}' on app_instance {app_instance_id}",
        ok=True,
        output=result.output,
        artifact_ids=[str(a) for a in result.artifacts],
        spend_usd=str(result.spend_usd),
        duration_seconds=round(result.duration_seconds, 4),
    )


def register_invoke_app_action_tool(registry):
    """Register invoke_app_action tool."""

    registry.register(
        Tool(
            name="invoke_app_action",
            description=(
                "Invoke a typed callable action on an installed Tesslate App. "
                "Returns the action's typed output (validated against its "
                "declared output_schema). Use this to compose installed apps "
                "from chat — pass the app_instance_id, the action_name from "
                "the app's manifest, and an input dict that matches the "
                "action's input_schema. Returns {ok: True, output, "
                "artifact_ids, spend_usd, duration_seconds} on success or "
                "{ok: False, error, error_message} on a typed dispatch error."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_instance_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "The UUID of the installed app instance to invoke.",
                    },
                    "action_name": {
                        "type": "string",
                        "description": "The name of the action as declared in the "
                        "app's manifest (e.g., 'summarize_pipeline').",
                    },
                    "input": {
                        "type": "object",
                        "description": "Input payload — must validate against the "
                        "action's declared input_schema. Defaults to an empty "
                        "object when omitted.",
                    },
                },
                "required": ["app_instance_id", "action_name"],
            },
            executor=invoke_app_action_executor,
            category=ToolCategory.PROJECT,
            # UUID + name + JSON dict in, JSON dict out — fully serializable.
            state_serializable=True,
            # One-shot dispatch; the action_dispatcher does not retain handles
            # or open streams across the call boundary.
            holds_external_state=False,
            examples=[
                '{"tool_name": "invoke_app_action", "parameters": {'
                '"app_instance_id": "00000000-0000-0000-0000-000000000001", '
                '"action_name": "summarize_pipeline", '
                '"input": {"pipeline_id": "pl-42"}}}',
            ],
        )
    )

    logger.info("Registered 1 app_ops tool")
