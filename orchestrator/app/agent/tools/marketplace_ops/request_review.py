"""``request_review`` — emit an in-chat publish/activate confirmation card.

The agent-builder calls this once it has finished drafting a child
:class:`MarketplaceAgent` (and optionally an
:class:`AutomationDefinition`). The tool:

1. Registers a pending approval via :class:`ApprovalManager`. The
   ``parameters`` payload carries the draft summary the chat-side
   ``BuilderReviewCard`` renders.
2. Publishes a ``builder_review_required`` SSE event so the chat UI can
   surface the card immediately. The event reuses the existing approval
   transport (``/api/chat/agent/approval`` posts the user's choice back
   to the same :class:`ApprovalManager`).
3. **Waits inline** for the user's choice (300s default cap) and
   applies the side effects directly:

   * ``publish_and_activate`` → flip
     :attr:`MarketplaceAgent.is_published` to ``True`` AND, if
     ``automation_id`` was supplied, flip
     :attr:`AutomationDefinition.is_active` to ``True``. Both writes
     happen in the same transaction.
   * ``save_draft`` → no DB writes; the user can publish later from
     the Library UI.
   * ``cancel`` → no DB writes; the agent is expected to offer a revise.

Returning the final state inline keeps the agent loop simple — it
reads the result and emits one short closing message.

Required scope: ``marketplace.author`` (and ``automations.write`` if
``automation_id`` is provided — checked at flip time).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ....models import MarketplaceAgent
from ....models_automations import AutomationDefinition
from ....services.automations.scopes import AUTOMATIONS_WRITE, MARKETPLACE_AUTHOR
from ..approval_manager import (
    get_approval_manager,
    wait_for_approval_or_cancel,
)
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


_VALID_RESPONSES = {"publish_and_activate", "save_draft", "cancel"}
_REVIEW_TIMEOUT_SECONDS = 600.0  # 10 minutes — humans need time to read.


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def request_review_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    agent_id = _coerce_uuid(params.get("agent_id"))
    automation_id = _coerce_uuid(params.get("automation_id"))
    summary = params.get("summary") or {}

    if agent_id is None:
        return error_output(message="agent_id is required (UUID)")
    if not isinstance(summary, dict):
        return error_output(message="summary must be an object")

    db = context.get("db")
    user_id = context.get("user_id")
    if db is None or user_id is None:
        return error_output(message="missing db/user_id in execution context")

    allowed_scopes = set(context.get("allowed_scopes") or [])
    if allowed_scopes and MARKETPLACE_AUTHOR not in allowed_scopes:
        return error_output(message=f"missing required scope: {MARKETPLACE_AUTHOR}")

    # Resolve + validate the agent. Reject built-in / system rows so a
    # rogue agent run can't surface a card that flips a platform agent's
    # is_published flag, even with the right approval id.
    agent_row = (
        await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    ).scalar_one_or_none()
    if agent_row is None:
        return error_output(message=f"agent {agent_id} not found")
    if agent_row.is_builtin or agent_row.is_system:
        return error_output(
            message="cannot request review for built-in or system agents"
        )
    if str(agent_row.created_by_user_id) != str(user_id):
        return error_output(message="agent is owned by another user")

    automation_row: AutomationDefinition | None = None
    if automation_id is not None:
        automation_row = (
            await db.execute(
                select(AutomationDefinition).where(
                    AutomationDefinition.id == automation_id
                )
            )
        ).scalar_one_or_none()
        if automation_row is None:
            return error_output(message=f"automation {automation_id} not found")
        if str(automation_row.owner_user_id) != str(user_id):
            return error_output(message="automation is owned by another user")
        # Activating an automation requires automations.write.
        if allowed_scopes and AUTOMATIONS_WRITE not in allowed_scopes:
            return error_output(
                message=f"missing required scope: {AUTOMATIONS_WRITE}"
            )

    session_id = (
        context.get("chat_id")
        or context.get("session_id")
        or context.get("automation_run_id")
        or "unknown"
    )
    task_id = context.get("task_id")
    pubsub = context.get("pubsub")

    # Register the approval. The chat hook resolves responses via the
    # existing /api/chat/agent/approval endpoint, which calls
    # respond_to_approval(approval_id, response) on this same manager.
    manager = get_approval_manager()
    approval_id, request = await manager.request_approval(
        tool_name="request_review",
        parameters={
            "kind": "builder_review",
            "agent_id": str(agent_id),
            "automation_id": str(automation_id) if automation_id else None,
            "summary": summary,
        },
        session_id=str(session_id),
    )

    # Surface the card on the chat stream. Without this publish, the
    # frontend wouldn't know an approval is pending — the SSE pipeline
    # is the only path between worker pod and chat UI.
    if pubsub is not None and task_id is not None:
        try:
            await pubsub.publish_agent_event(
                task_id,
                {
                    "type": "approval_required",
                    "data": {
                        "approval_id": approval_id,
                        "tool": "request_review",
                        "tool_name": "request_review",
                        "kind": "builder_review",
                        "summary": summary,
                        "agent_id": str(agent_id),
                        "automation_id": (
                            str(automation_id) if automation_id else None
                        ),
                        "session_id": str(session_id),
                    },
                },
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "[request_review] failed to publish approval event for %s",
                approval_id,
            )

    logger.info(
        "[request_review] awaiting builder_review approval=%s agent=%s automation=%s",
        approval_id,
        agent_id,
        automation_id,
    )

    response = await wait_for_approval_or_cancel(
        request,
        task_id=str(task_id) if task_id else None,
        timeout_seconds=_REVIEW_TIMEOUT_SECONDS,
    )

    # Normalise: timeouts and cancellations both fall through to "cancel"
    # semantics (no DB writes); the agent is expected to follow up with
    # the user. We surface the distinction in the result so the final
    # message can be tailored.
    if response is None:
        outcome = "timeout"
    elif response in {"cancel", "stop"}:
        outcome = "cancel"
    elif response == "save_draft":
        outcome = "save_draft"
    elif response == "publish_and_activate":
        outcome = "publish_and_activate"
    elif response not in _VALID_RESPONSES:
        # Unknown response string — treat as cancel rather than guess.
        logger.warning(
            "[request_review] unknown response %r for approval=%s",
            response,
            approval_id,
        )
        outcome = "cancel"
    else:
        outcome = response

    if outcome == "publish_and_activate":
        agent_row.is_published = True
        if automation_row is not None:
            automation_row.is_active = True
            automation_row.paused_reason = None
        await db.commit()
        logger.info(
            "[request_review] published agent=%s automation_active=%s",
            agent_id,
            automation_row is not None,
        )
        return success_output(
            message=f"Published {agent_row.name!r} and activated its automation.",
            outcome="published",
            agent_id=str(agent_id),
            agent_slug=agent_row.slug,
            automation_id=str(automation_id) if automation_id else None,
            is_published=True,
            is_active=automation_row.is_active if automation_row else None,
        )

    if outcome == "save_draft":
        return success_output(
            message=(
                f"Saved {agent_row.name!r} as a draft. The user can publish "
                "it later from /library?tab=agents."
            ),
            outcome="saved_draft",
            agent_id=str(agent_id),
            agent_slug=agent_row.slug,
            automation_id=str(automation_id) if automation_id else None,
            is_published=False,
            is_active=False if automation_row else None,
        )

    if outcome == "timeout":
        return success_output(
            message=(
                "No response within the review window. The draft is still "
                "saved; mention me again to revisit it."
            ),
            outcome="timeout",
            agent_id=str(agent_id),
            agent_slug=agent_row.slug,
            automation_id=str(automation_id) if automation_id else None,
            is_published=False,
            is_active=False if automation_row else None,
        )

    # Cancel / stop / unknown — the user wants to revise.
    return success_output(
        message=(
            f"User declined to publish {agent_row.name!r}. The draft is "
            "saved; ask them what they want to change."
        ),
        outcome="cancel",
        agent_id=str(agent_id),
        agent_slug=agent_row.slug,
        automation_id=str(automation_id) if automation_id else None,
        is_published=False,
        is_active=False if automation_row else None,
    )


def register_request_review_tool(registry):
    registry.register(
        Tool(
            name="request_review",
            description=(
                "Surface an in-chat review card asking the user to publish "
                "the drafted agent and activate its automation. Blocks "
                "until the user clicks Publish & Activate / Save as draft / "
                "Cancel (10-minute cap), then applies the chosen side "
                "effect and returns the outcome. Required scopes: "
                "marketplace.author (always), automations.write (when "
                "automation_id is provided)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UUID of the draft MarketplaceAgent to review.",
                    },
                    "automation_id": {
                        "type": "string",
                        "description": (
                            "Optional UUID of the AutomationDefinition created "
                            "for the agent. When supplied, an approve flips "
                            "is_active=True alongside the agent's is_published."
                        ),
                    },
                    "summary": {
                        "type": "object",
                        "description": (
                            "Display payload for the chat card. Shape: "
                            "{name, description, mcps:[{slug,name}], "
                            "schedule:{cron,tz,humanized}, "
                            "delivery_targets:[{kind,name}], draft_url}."
                        ),
                    },
                },
                "required": ["agent_id", "summary"],
            },
            executor=request_review_executor,
            category=ToolCategory.PROJECT,
            # The wait happens inline but uses asyncio events — no socket
            # / pty held open. Outputs are JSON-clean.
            state_serializable=True,
            holds_external_state=False,
        )
    )
