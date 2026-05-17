"""``read_workflow_history`` agent tool (G2, issue #469).

Read-only summary of a workflow's recent runs + events + the head
version. The doctor agent (G5) calls this to diagnose before
proposing a change.

Returns:

    {
      "automation_id": ...,
      "head_version_id": ...,
      "head_payload": {...},
      "runs": [
        {"id": ..., "status": ..., "started_at": ..., "ended_at": ...,
         "spend_usd": ..., "workflow_version_id": ...,
         "step_summary": [{"ordinal": 0, "kind": "...", "status": ...,
                           "error": ...}],
         "event_kinds": ["step.started", ...]}
      ]
    }

Bounded: caller picks ``limit`` (max 50). The doctor typically asks
for 10 most recent.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def read_workflow_history_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    automation_id_raw = params.get("automation_id")
    limit = int(params.get("limit") or 10)
    if limit < 1 or limit > 50:
        limit = max(1, min(50, limit))

    db = context.get("db")
    user_id = context.get("user_id")
    contract = context.get("contract") or {}

    if not automation_id_raw:
        return error_output(message="automation_id is required")
    if db is None:
        return error_output(message="database session not available in context")

    try:
        automation_id = UUID(str(automation_id_raw))
    except (TypeError, ValueError):
        return error_output(message=f"invalid automation_id {automation_id_raw!r}")

    # Scope: a contract carrying ``allowed_workflow_ids`` (the G5 doctor)
    # constrains which automations are readable even though the caller
    # may own others.
    raw_allowed = contract.get("allowed_workflow_ids") if isinstance(contract, dict) else None
    allowed_workflow_ids: set[str] | None = None
    if isinstance(raw_allowed, list) and raw_allowed:
        allowed_workflow_ids = {str(x) for x in raw_allowed}

    from ....models_automations import (
        AutomationDefinition,
        AutomationRun,
        AutomationRunEvent,
        AutomationStepRun,
    )
    from ....models_workflows import WorkflowVersion

    automation = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == automation_id)
        )
    ).scalar_one_or_none()
    if automation is None:
        return error_output(message=f"automation {automation_id} not found")
    if user_id is not None and str(automation.owner_user_id) != str(user_id):
        return error_output(message="automation not visible to caller")
    if allowed_workflow_ids is not None and str(automation.id) not in allowed_workflow_ids:
        return error_output(message="automation not in caller's allowed scope")

    head_payload = None
    if automation.head_version_id is not None:
        head = (
            await db.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == automation.head_version_id)
            )
        ).scalar_one_or_none()
        head_payload = head.payload if head is not None else None

    runs = (
        (
            await db.execute(
                select(AutomationRun)
                .where(AutomationRun.automation_id == automation_id)
                .order_by(AutomationRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    run_summaries: list[dict[str, Any]] = []
    for run in runs:
        steps = (
            (
                await db.execute(
                    select(AutomationStepRun)
                    .where(AutomationStepRun.automation_run_id == run.id)
                    .order_by(AutomationStepRun.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        events = (
            (
                await db.execute(
                    select(AutomationRunEvent)
                    .where(AutomationRunEvent.automation_run_id == run.id)
                    .order_by(AutomationRunEvent.ts.asc())
                )
            )
            .scalars()
            .all()
        )
        run_summaries.append(
            {
                "id": str(run.id),
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "spend_usd": str(run.spend_usd) if run.spend_usd is not None else None,
                "workflow_version_id": (
                    str(run.workflow_version_id) if run.workflow_version_id else None
                ),
                "step_summary": [
                    {
                        "ordinal": s.ordinal,
                        "kind": s.kind,
                        "status": s.status,
                        "error": s.error,
                    }
                    for s in steps
                ],
                "event_kinds": [e.kind for e in events],
            }
        )

    return success_output(
        message=f"{len(run_summaries)} runs",
        automation_id=str(automation.id),
        head_version_id=(str(automation.head_version_id) if automation.head_version_id else None),
        head_payload=head_payload,
        runs=run_summaries,
    )


def register_read_workflow_history_tool(registry) -> None:
    registry.register(
        Tool(
            name="read_workflow_history",
            description=(
                "Read the most recent N runs of an automation you own, "
                "including step outcomes, errors, spend, version id, and "
                "the kinds of events emitted. Returns the head version's "
                "full payload so you can compare proposed changes against "
                "the current shape. Use this BEFORE creating a workflow "
                "proposal to diagnose what's actually failing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "automation_id": {
                        "type": "string",
                        "description": "Automation UUID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent runs to include (1-50; default 10)",
                    },
                },
                "required": ["automation_id"],
            },
            executor=read_workflow_history_executor,
            category=ToolCategory.PROJECT,
            state_serializable=True,
            holds_external_state=False,
            compute_tier=0,
            examples=[
                '{"tool_name": "read_workflow_history", "parameters": {"automation_id": "...", "limit": 10}}',
            ],
        )
    )
    logger.info("Registered 1 read_workflow_history tool")
