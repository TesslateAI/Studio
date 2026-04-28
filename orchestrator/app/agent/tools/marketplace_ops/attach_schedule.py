"""``attach_schedule`` — create a child :class:`AutomationDefinition`.

The agent-builder skill calls this to attach a cron / webhook /
event-driven schedule to a draft agent. The created definition is a
CHILD of the parent automation that ran the tool:

- ``parent_automation_id`` = ``context['automation_id']``
- ``depth`` = ``parent.depth + 1`` (capped at 1 by the DB CHECK
  ``ck_automation_definitions_depth_range``).

Validation pass — all three must succeed before the row is inserted:

1.  ``ctx.automation.depth < 1`` — depth-1 cap. If we're already at
    depth 1 we'd be creating a depth-2 grandchild; reject with
    ``depth_exceeded``.
2.  Child contract is a legal restriction of the parent contract per
    :func:`services.automations.contract.validate_child_contract`. This
    catches both per-run cap and positive-list scope violations in one
    pass.
3.  Required scope: ``automations.write``.

The created definition is inserted with ``is_active=False`` so the user
must explicitly enable it in the UI before it starts firing — same
"draft until human approves" pattern as ``create_agent``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ....services.automations.scopes import AUTOMATIONS_WRITE
from ....models import MarketplaceAgent
from ....models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationDeliveryTarget,
    AutomationTrigger,
    CommunicationDestination,
)
from ...tools.output_formatter import error_output, success_output
from ...tools.registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


_VALID_TRIGGER_KINDS = {"cron", "webhook", "app_invocation", "manual"}
_VALID_WORKSPACE_SCOPES = {
    "none",
    "user_automation_workspace",
    "team_automation_workspace",
    "target_project",
}


async def attach_schedule_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    agent_id_raw = params.get("agent_id")
    trigger = params.get("trigger")
    prompt_template = params.get("prompt_template")
    contract = params.get("contract")
    delivery_targets = params.get("delivery_targets") or []
    workspace_scope = params.get("workspace_scope", "user_automation_workspace")
    max_compute_tier = int(params.get("max_compute_tier", 0) or 0)

    if not agent_id_raw or not isinstance(trigger, dict) or not prompt_template:
        return error_output(
            message="agent_id, trigger (dict), and prompt_template are required"
        )
    if not isinstance(contract, dict):
        return error_output(message="contract (dict) is required")
    if workspace_scope not in _VALID_WORKSPACE_SCOPES:
        return error_output(
            message=f"workspace_scope must be one of {sorted(_VALID_WORKSPACE_SCOPES)}"
        )

    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    allowed_scopes = set(context.get("allowed_scopes") or [])
    if AUTOMATIONS_WRITE not in allowed_scopes:
        return error_output(message=f"missing required scope: {AUTOMATIONS_WRITE}")

    try:
        agent_id = UUID(str(agent_id_raw))
    except (TypeError, ValueError):
        return error_output(message=f"invalid agent_id: {agent_id_raw!r}")

    # Trigger validation.
    trigger_kind = trigger.get("kind")
    if trigger_kind not in _VALID_TRIGGER_KINDS:
        return error_output(
            message=f"trigger.kind must be one of {sorted(_VALID_TRIGGER_KINDS)}"
        )
    trigger_config = trigger.get("config") or {}
    if not isinstance(trigger_config, dict):
        return error_output(message="trigger.config must be a dict")

    # Resolve parent automation. The dispatcher passes the row id via
    # ``context['automation_id']``; tool-driven creates outside an
    # automation run (e.g., during local dev) have no parent and are
    # treated as depth=0 roots.
    parent_automation_id_raw = context.get("automation_id")
    parent_automation: AutomationDefinition | None = None
    parent_id: UUID | None = None
    if parent_automation_id_raw is not None:
        try:
            parent_id = UUID(str(parent_automation_id_raw))
        except (TypeError, ValueError):
            return error_output(
                message=f"invalid context.automation_id: {parent_automation_id_raw!r}"
            )
        parent_automation = (
            await db.execute(
                select(AutomationDefinition).where(
                    AutomationDefinition.id == parent_id
                )
            )
        ).scalar_one_or_none()
        if parent_automation is None:
            return error_output(
                message=f"parent automation {parent_id} not found"
            )

        # Depth-1 cap. Parent at depth 1 -> child would be depth 2 ->
        # the DB CHECK would reject anyway, but we surface a typed
        # error first so the user sees a clear reason.
        if parent_automation.depth >= 1:
            return error_output(
                message="depth_exceeded: agent-builder skill enforces depth-1 cap",
                suggestion=(
                    "Refactor the parent automation to spawn the child directly "
                    "rather than creating a grandchild."
                ),
            )

        # Contract inheritance check (per-run cap + positive-list scopes).
        from ....services.automations.contract import (
            ContractInheritanceError,
            validate_child_contract,
        )

        try:
            validate_child_contract(parent_automation.contract or {}, contract)
        except ContractInheritanceError as exc:
            return error_output(
                message=f"contract inheritance violation: {exc.code}: {exc}",
                suggestion="Adjust the child contract to a strict subset of the parent.",
            )

    # Validate the agent exists and is owned by the current user.
    agent = (
        await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        return error_output(message=f"agent {agent_id} not found")
    if agent.created_by_user_id != user_id and agent.forked_by_user_id != user_id:
        return error_output(message="not the owner of this agent")

    # Validate delivery targets reference real CommunicationDestination
    # rows owned by the current user. Empty list is OK — silent runs are
    # legitimate (user pulls history from the UI).
    if delivery_targets and not isinstance(delivery_targets, list):
        return error_output(message="delivery_targets must be a list of UUID strings")
    resolved_dest_ids: list[UUID] = []
    for dt_raw in delivery_targets:
        try:
            dt_id = UUID(str(dt_raw))
        except (TypeError, ValueError):
            return error_output(message=f"invalid delivery target id: {dt_raw!r}")
        dest = (
            await db.execute(
                select(CommunicationDestination.id, CommunicationDestination.owner_user_id).where(
                    CommunicationDestination.id == dt_id
                )
            )
        ).first()
        if dest is None:
            return error_output(message=f"destination {dt_id} not found")
        if dest.owner_user_id is not None and dest.owner_user_id != user_id:
            return error_output(message=f"destination {dt_id} not owned by current user")
        resolved_dest_ids.append(dt_id)

    # All checks passed. Create the rows.
    automation = AutomationDefinition(
        name=params.get("name") or f"agent-builder schedule for {agent.name}",
        owner_user_id=user_id,
        team_id=context.get("team_id"),
        workspace_scope=workspace_scope,
        contract=contract,
        max_compute_tier=max_compute_tier,
        max_spend_per_run_usd=contract.get("max_spend_per_run_usd"),
        max_spend_per_day_usd=contract.get("max_spend_per_day_usd"),
        parent_automation_id=parent_id,
        depth=(parent_automation.depth + 1) if parent_automation is not None else 0,
        # CRITICAL: tool-driven creates are inactive until the user
        # explicitly enables them in the UI. Mirrors create_agent's
        # draft-only invariant.
        is_active=False,
        created_by_user_id=user_id,
        created_by_automation_id=parent_id,
    )
    db.add(automation)
    await db.flush()

    db.add(
        AutomationTrigger(
            automation_id=automation.id,
            kind=trigger_kind,
            config=trigger_config,
            is_active=False,
        )
    )

    db.add(
        AutomationAction(
            automation_id=automation.id,
            ordinal=0,
            action_type="agent.run",
            config={
                "agent_id": str(agent_id),
                "prompt_template": prompt_template,
            },
        )
    )

    for ordinal, dest_id in enumerate(resolved_dest_ids):
        db.add(
            AutomationDeliveryTarget(
                automation_id=automation.id,
                destination_id=dest_id,
                ordinal=ordinal,
            )
        )

    await db.commit()
    await db.refresh(automation)

    logger.info(
        "marketplace_ops.attach_schedule automation=%s parent=%s agent=%s user=%s",
        automation.id,
        parent_id,
        agent_id,
        user_id,
    )
    return success_output(
        message=(
            f"Drafted automation {automation.name!r}. "
            f"automation_id={automation.id} agent_id={agent_id} "
            f"depth={automation.depth} is_active=False. "
            f"Use this exact automation_id for the next request_review call."
        ),
        automation_id=str(automation.id),
        depth=automation.depth,
        parent_automation_id=str(parent_id) if parent_id else None,
        is_active=False,
    )


def register_attach_schedule_tool(registry):
    registry.register(
        Tool(
            name="attach_schedule",
            description=(
                "Create a draft AutomationDefinition that runs a target agent "
                "on a trigger (cron/webhook/app_invocation/manual). The new "
                "automation is a CHILD of the parent automation that called "
                "this tool — depth-1 cap enforced. The contract must be a "
                "strict restriction of the parent's contract (per-run cap + "
                "positive-list scopes). Created with is_active=False; user "
                "enables in UI. Required scope: automations.write."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Draft agent UUID"},
                    "trigger": {
                        "type": "object",
                        "description": "{kind, config} — kind is cron|webhook|app_invocation|manual",
                    },
                    "prompt_template": {
                        "type": "string",
                        "description": "Body sent to the agent on each run",
                    },
                    "contract": {
                        "type": "object",
                        "description": "Run-time contract (must restrict parent's)",
                    },
                    "delivery_targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of CommunicationDestination UUIDs",
                    },
                    "workspace_scope": {
                        "type": "string",
                        "enum": [
                            "none",
                            "user_automation_workspace",
                            "team_automation_workspace",
                            "target_project",
                        ],
                    },
                    "max_compute_tier": {"type": "integer", "minimum": 0, "maximum": 2},
                    "name": {"type": "string"},
                },
                "required": [
                    "agent_id",
                    "trigger",
                    "prompt_template",
                    "contract",
                ],
            },
            executor=attach_schedule_executor,
            category=ToolCategory.PROJECT,
            state_serializable=True,
            holds_external_state=False,
        )
    )
