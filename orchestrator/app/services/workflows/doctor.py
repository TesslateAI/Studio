"""Per-workflow doctor lifecycle (G5, issue #469).

The "doctor" is an ``AutomationDefinition`` whose job is to watch
ONE target workflow's run.failed events, diagnose, and write
``WorkflowProposal`` rows against it. It runs in the same engine
as any other workflow — no new control plane.

Public API:

* :func:`ensure_doctor_for` — idempotently create / re-use a doctor
  bound to a target automation. Sets target.doctor_automation_id +
  target.doctor_enabled=True.
* :func:`disable_doctor_for` — sets doctor_enabled=False (leaves the
  doctor row in place so re-enabling is one flag flip).

The doctor's shape (initial Phase G5):

  trigger: workflow_event { watched_automation_id, event_kinds=[run.failed, error.raised] }
  actions:
    ordinal 0: agent.run with prompt: "diagnose then propose"
      contract: { allowed_tools: [read_workflow_history, manage_workflow_proposal,
                                   send_message],
                  max_compute_tier: 0,
                  allowed_workflow_ids: [<target_id>] }
      compute_profile: connector_only

The agent.run handler executes against connector_only so the doctor
itself has no workspace. The actual diagnose+propose loop is the
LLM's job — we don't hardcode logic.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationTrigger,
)
from .versions import snapshot_definition_to_version

logger = logging.getLogger(__name__)


def _doctor_contract(target_id: UUID) -> dict[str, Any]:
    return {
        "allowed_tools": [
            "read_workflow_history",
            "manage_workflow_proposal",
            "send_message",
        ],
        "max_compute_tier": 0,
        "on_breach": "pause_for_approval",
        "allowed_workflow_ids": [str(target_id)],
        "rationale": "doctor scope: only the target workflow",
    }


def _doctor_prompt(target_id: UUID) -> str:
    return (
        f"You are the workflow doctor for automation {target_id}. A run "
        "just failed. Use `read_workflow_history` to inspect the most "
        "recent runs + the head version's payload. Identify the most "
        "likely cause. If you can propose a targeted fix, call "
        "`manage_workflow_proposal` with action=create. Otherwise call "
        "`send_message` to alert the owner. Keep proposals small and "
        "use risk_class=low when the change is textual."
    )


async def ensure_doctor_for(
    db: AsyncSession,
    *,
    target_automation: AutomationDefinition,
) -> AutomationDefinition:
    """Idempotently create a doctor for the target. Sets pointers.

    Caller is responsible for committing.

    Returns the doctor AutomationDefinition row.
    """
    if target_automation.doctor_automation_id is not None:
        existing = (
            await db.execute(
                select(AutomationDefinition).where(
                    AutomationDefinition.id == target_automation.doctor_automation_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            target_automation.doctor_enabled = True
            return existing

    target_id = target_automation.id
    doctor = AutomationDefinition(
        id=uuid.uuid4(),
        name=f"doctor:{target_automation.name}",
        owner_user_id=target_automation.owner_user_id,
        team_id=target_automation.team_id,
        workspace_scope="none",
        contract=_doctor_contract(target_id),
        max_compute_tier=0,
        compute_profile="connector_only",
        is_active=True,
        parent_automation_id=target_id,
        depth=1,  # depth-1 cap from the agent-builder skill
    )
    db.add(doctor)
    await db.flush()

    db.add(
        AutomationTrigger(
            id=uuid.uuid4(),
            automation_id=doctor.id,
            kind="workflow_event",
            config={
                "watched_automation_id": str(target_id),
                "event_kinds": ["run.failed", "error.raised", "step.failed"],
            },
            is_active=True,
        )
    )
    db.add(
        AutomationAction(
            id=uuid.uuid4(),
            automation_id=doctor.id,
            ordinal=0,
            action_type="agent.run",
            config={
                "prompt": _doctor_prompt(target_id),
                "target_automation_id": str(target_id),
            },
        )
    )

    # Snapshot the doctor as generation 1 so its own runs are
    # version-bound from the start.
    await snapshot_definition_to_version(
        db,
        definition=doctor,
        rationale=f"doctor bootstrap for target={target_id}",
        actor_user_id=target_automation.owner_user_id,
        update_head=True,
    )

    target_automation.doctor_automation_id = doctor.id
    target_automation.doctor_enabled = True

    logger.info(
        "doctor.created target=%s doctor=%s",
        target_id,
        doctor.id,
    )
    return doctor


async def disable_doctor_for(
    db: AsyncSession,
    *,
    target_automation: AutomationDefinition,
) -> None:
    """Flip the flag off. Leaves the doctor row in place so re-enable
    is idempotent."""
    target_automation.doctor_enabled = False
    # Also deactivate the doctor's trigger so it stops firing.
    if target_automation.doctor_automation_id is not None:
        trigs = (
            (
                await db.execute(
                    select(AutomationTrigger).where(
                        AutomationTrigger.automation_id == target_automation.doctor_automation_id,
                        AutomationTrigger.kind == "workflow_event",
                    )
                )
            )
            .scalars()
            .all()
        )
        for t in trigs:
            t.is_active = False
