"""``request_grant`` — register an approval card asking for a capability.

When the agent realises it needs a capability the run doesn't have
(e.g. an OAuth grant for a Linear MCP, or write access to a project the
user owns but hasn't explicitly granted), it calls this tool. The tool:

1.  Registers a pending approval via the existing
    :class:`ApprovalManager`. The approval id is returned to the agent so
    it can either ``await`` the resolution (wait-cap pattern) or persist
    the id to a checkpoint and let the dispatcher resume the run after
    the user responds.
2.  Returns immediately with ``{approval_id}``. The agent loop is
    responsible for the wait — this tool itself NEVER blocks the
    pre-tool-call gate (matches the non-blocking HITL pattern in
    ``services/automations/dispatcher.py``).

The wait pattern is the same one the existing approval-aware tools use
in ``approval_manager.py``: store the id, exit the tool, let the
dispatcher checkpoint + resume.
"""

from __future__ import annotations

import logging
from typing import Any

from ....services.automations.scopes import is_inheritable
from ..approval_manager import get_approval_manager
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


_VALID_RESOURCE_KINDS = {
    "project",
    "team",
    "mcp_server",
    "channel_destination",
    "deployment_credential",
    "external_api_key",
}


async def request_grant_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    resource = params.get("resource")
    capability = params.get("capability")
    if not isinstance(resource, dict) or not capability:
        return error_output(
            message="resource (dict with kind+id) and capability (string) are required"
        )

    resource_kind = resource.get("kind")
    resource_id = resource.get("id")
    if resource_kind not in _VALID_RESOURCE_KINDS:
        return error_output(
            message=f"resource.kind must be one of {sorted(_VALID_RESOURCE_KINDS)}"
        )
    if not resource_id:
        return error_output(message="resource.id is required")
    if not isinstance(capability, str) or "." not in capability:
        # We require dotted scope syntax (e.g., "mcp.linear.read") so
        # the granted capability slots cleanly into the contract.
        return error_output(
            message="capability must be a dotted scope string (e.g. 'mcp.linear.read')"
        )

    # Hint to the agent: capabilities outside the inheritable positive
    # list cannot live on a child contract. We still allow the request
    # (the user might be granting it on the PARENT automation) but flag
    # it so the agent knows to handle the rejection cleanly.
    if not is_inheritable(capability):
        non_inheritable_warning = True
    else:
        non_inheritable_warning = False

    session_id = (
        context.get("chat_id")
        or context.get("session_id")
        or context.get("automation_run_id")
        or "unknown"
    )

    manager = get_approval_manager()
    approval_id, _request = await manager.request_approval(
        tool_name="request_grant",
        parameters={
            "resource": resource,
            "capability": capability,
            "automation_id": context.get("automation_id"),
            "automation_run_id": context.get("automation_run_id"),
            "kind": "grant_request",
        },
        session_id=str(session_id),
    )

    logger.info(
        "marketplace_ops.request_grant approval=%s capability=%s resource=%s session=%s",
        approval_id,
        capability,
        resource,
        session_id,
    )
    return success_output(
        message=(
            f"Grant requested for {capability!r} on "
            f"{resource_kind}={resource_id}; awaiting user approval."
        ),
        approval_id=approval_id,
        capability=capability,
        resource=resource,
        non_inheritable=non_inheritable_warning,
        # The agent loop should checkpoint on this id and wait for
        # ``ApprovalManager.respond_to_approval`` (or the resume
        # path in the dispatcher) before proceeding with the gated work.
        wait_pattern="checkpoint_and_resume",
    )


def register_request_grant_tool(registry):
    registry.register(
        Tool(
            name="request_grant",
            description=(
                "Register an approval card asking the user to grant a "
                "capability the run doesn't have. Returns an approval_id "
                "immediately — the agent loop must checkpoint on it and "
                "wait for the user response (non-blocking HITL pattern)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "object",
                        "description": "{kind, id} — what the capability scopes to",
                        "properties": {
                            "kind": {"type": "string", "enum": sorted(_VALID_RESOURCE_KINDS)},
                            "id": {"type": "string"},
                        },
                        "required": ["kind", "id"],
                    },
                    "capability": {
                        "type": "string",
                        "description": "Dotted scope string (e.g., 'mcp.linear.read')",
                    },
                },
                "required": ["resource", "capability"],
            },
            executor=request_grant_executor,
            category=ToolCategory.PROJECT,
            # The approval id is JSON-clean. The wait happens elsewhere
            # (agent loop / dispatcher); this tool itself never blocks.
            state_serializable=True,
            # The PendingUserInputManager singleton holds the unresolved
            # request; the tool handle out doesn't itself own a socket.
            holds_external_state=False,
        )
    )
