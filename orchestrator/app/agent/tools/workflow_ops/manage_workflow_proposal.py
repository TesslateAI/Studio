"""``manage_workflow_proposal`` agent tool (G2, issue #469).

Agents call this to draft changes to an automation they own. The
proposal is persisted via :mod:`services.workflows.proposals` and
routes through the existing manual-approval pipeline (G2 always
routes through approval; G3 wires the auto-apply path).

Actions:
    create: draft a new proposal against an automation
    list:   list proposals on an automation (optionally by status)
    get:    fetch one proposal with full payload + diff
    withdraw: cancel a submitted proposal

Authority + scope:
    The tool refuses to operate on an automation the calling user
    does not own (or have team write access to). The doctor agent's
    contract (G5) will further scope by automation_id allow-list so
    a doctor for workflow X can only touch workflow X.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def manage_workflow_proposal_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    action = params.get("action")
    db = context.get("db")
    user_id = context.get("user_id")
    run_id = context.get("automation_run_id")

    if not action:
        return error_output(message="action parameter is required")
    if db is None:
        return error_output(message="database session not available in context")
    if user_id is None and run_id is None:
        return error_output(message="agent context has no user_id or automation_run_id")

    from ....models_automations import AutomationDefinition
    from ....services.workflows.proposals import (
        ProposalAlreadyDecided,
        ProposalError,
        ProposalNotFound,
        create_proposal,
        get_proposal,
        list_proposals,
        withdraw_proposal,
    )

    async def _load_owned_automation(automation_id_str: str) -> AutomationDefinition | None:
        try:
            aid = UUID(automation_id_str)
        except (TypeError, ValueError):
            return None
        row = (
            await db.execute(select(AutomationDefinition).where(AutomationDefinition.id == aid))
        ).scalar_one_or_none()
        if row is None:
            return None
        # Owner-only for now. G5 doctor will scope via contract.allowed_workflow_ids.
        if user_id is not None and str(row.owner_user_id) != str(user_id):
            return None
        return row

    if action == "create":
        automation_id = params.get("automation_id")
        to_payload = params.get("to_payload")
        rationale = params.get("rationale")
        if not (automation_id and isinstance(to_payload, dict) and rationale):
            return error_output(
                message="create requires automation_id, to_payload (object), and rationale"
            )
        automation = await _load_owned_automation(automation_id)
        if automation is None:
            return error_output(message=f"automation {automation_id} not found or not owned")
        try:
            result = await create_proposal(
                db,
                automation=automation,
                to_payload=to_payload,
                rationale=str(rationale),
                risk_class=str(params.get("risk_class") or "medium"),
                proposer_user_id=UUID(str(user_id)) if user_id else None,
                proposer_run_id=UUID(str(run_id)) if run_id else None,
            )
        except ProposalError as exc:
            return error_output(message=str(exc))
        await db.commit()
        await db.refresh(result.proposal)
        return success_output(
            message=(
                f"Proposal {'created' if result.created else 'already submitted'} "
                f"for {automation.name}. Routed to approval queue."
            ),
            proposal_id=str(result.proposal.id),
            status=result.proposal.status,
            risk_class=result.proposal.risk_class,
            diff_entry_count=len(result.proposal.diff_summary or []),
            created=result.created,
        )

    if action == "list":
        automation_id = params.get("automation_id")
        if not automation_id:
            return error_output(message="list requires automation_id")
        automation = await _load_owned_automation(automation_id)
        if automation is None:
            return error_output(message=f"automation {automation_id} not found or not owned")
        rows = await list_proposals(
            db,
            automation_id=automation.id,
            status=params.get("status"),
        )
        return success_output(
            message=f"{len(rows)} proposals",
            proposals=[
                {
                    "id": str(p.id),
                    "status": p.status,
                    "risk_class": p.risk_class,
                    "rationale": p.rationale,
                    "diff_entry_count": len(p.diff_summary or []),
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "decided_at": p.decided_at.isoformat() if p.decided_at else None,
                }
                for p in rows
            ],
        )

    if action == "get":
        proposal_id = params.get("proposal_id")
        if not proposal_id:
            return error_output(message="get requires proposal_id")
        try:
            p = await get_proposal(db, proposal_id=UUID(proposal_id))
        except (ProposalNotFound, ValueError) as exc:
            return error_output(message=str(exc))
        # Scope check: load automation and verify ownership.
        automation = await _load_owned_automation(str(p.automation_id))
        if automation is None:
            return error_output(message="proposal not visible to caller")
        return success_output(
            message=f"proposal {p.status}",
            proposal_id=str(p.id),
            automation_id=str(p.automation_id),
            status=p.status,
            risk_class=p.risk_class,
            rationale=p.rationale,
            diff_summary=p.diff_summary,
            to_payload=p.to_payload,
            applied_version_id=(str(p.applied_version_id) if p.applied_version_id else None),
            created_at=p.created_at.isoformat() if p.created_at else None,
            decided_at=p.decided_at.isoformat() if p.decided_at else None,
        )

    if action == "withdraw":
        proposal_id = params.get("proposal_id")
        if not proposal_id:
            return error_output(message="withdraw requires proposal_id")
        try:
            p = await withdraw_proposal(
                db,
                proposal_id=UUID(proposal_id),
                actor_user_id=UUID(str(user_id)) if user_id else None,
                actor_run_id=UUID(str(run_id)) if run_id else None,
            )
        except (ProposalNotFound, ProposalAlreadyDecided, ValueError) as exc:
            return error_output(message=str(exc))
        await db.commit()
        return success_output(message=f"proposal {p.id} withdrawn", proposal_id=str(p.id))

    return error_output(message=f"unknown action {action!r}; must be create|list|get|withdraw")


def register_manage_workflow_proposal_tool(registry) -> None:
    registry.register(
        Tool(
            name="manage_workflow_proposal",
            description=(
                "Draft, list, inspect, or withdraw changes to an automation you own. "
                "Use 'create' with a full to_payload (same shape as the automation's "
                "head version payload) plus a rationale to propose an edit. The "
                "proposal routes through the approval queue and applies on approve. "
                "Use 'list' or 'get' to inspect existing proposals; 'withdraw' to "
                "cancel one you submitted."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Operation to perform",
                        "enum": ["create", "list", "get", "withdraw"],
                    },
                    "automation_id": {
                        "type": "string",
                        "description": "Automation UUID (required for create / list)",
                    },
                    "proposal_id": {
                        "type": "string",
                        "description": "Proposal UUID (required for get / withdraw)",
                    },
                    "to_payload": {
                        "type": "object",
                        "description": (
                            "Full proposed shape — contract, max_compute_tier, "
                            "max_spend_per_*_usd, compute_profile, workspace_scope, "
                            "name, actions[], triggers[], delivery_targets[]. "
                            "Same schema as a WorkflowVersion payload."
                        ),
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Short human-readable reason for the change",
                    },
                    "risk_class": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Caller's risk assessment; default medium",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter for list (submitted|approved|...)",
                    },
                },
                "required": ["action"],
            },
            executor=manage_workflow_proposal_executor,
            category=ToolCategory.PROJECT,
            state_serializable=True,
            holds_external_state=False,
            compute_tier=0,
            examples=[
                '{"tool_name": "manage_workflow_proposal", "parameters": {"action": "list", "automation_id": "..."}}',
                '{"tool_name": "manage_workflow_proposal", "parameters": {"action": "create", "automation_id": "...", "rationale": "increase timeout to absorb p95 latency", "risk_class": "low", "to_payload": {...}}}',
            ],
        )
    )
    logger.info("Registered 1 manage_workflow_proposal tool")
