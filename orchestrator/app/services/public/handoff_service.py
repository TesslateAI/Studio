"""Agent session handoff — serialize AgentTask state for local ↔ cloud moves.

The bundle shape is the stable contract between cloud and desktop clients.
Fields present in every bundle:

- `task_id`            — source task id (None for fresh uploads from desktop)
- `project_id`, `chat_id`
- `message`            — user-facing prompt for the next step
- `trajectory`         — list of `AgentStep.step_data` dicts, in order
- `file_diff`          — optional unified diff the desktop produced locally
- `goal_ancestry`      — optional chain of parent goals (caller-managed)
- `skill_bindings`     — list of skill slugs the source session had loaded
- `continuation_token` — opaque marker; cloud can ignore on upload but must
                          echo it back on download so the desktop can detect
                          replay gaps
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bundle dataclass
# ---------------------------------------------------------------------------


@dataclass
class HandoffBundle:
    project_id: str
    chat_id: str
    message: str
    task_id: str | None = None
    trajectory: list[dict] = field(default_factory=list)
    file_diff: str | None = None
    goal_ancestry: list[str] = field(default_factory=list)
    skill_bindings: list[str] = field(default_factory=list)
    continuation_token: str | None = None
    agent_id: str | None = None
    container_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "chat_id": self.chat_id,
            "message": self.message,
            "trajectory": self.trajectory,
            "file_diff": self.file_diff,
            "goal_ancestry": self.goal_ancestry,
            "skill_bindings": self.skill_bindings,
            "continuation_token": self.continuation_token,
            "agent_id": self.agent_id,
            "container_name": self.container_name,
        }


# ---------------------------------------------------------------------------
# Continuation tokens — opaque base64(JSON)
# ---------------------------------------------------------------------------


def make_continuation_token(chat_id: str, last_step_index: int) -> str:
    raw = json.dumps({"chat_id": chat_id, "step": last_step_index}, sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


def parse_continuation_token(token: str) -> dict[str, Any]:
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + padding).decode()
        return json.loads(raw)
    except Exception as exc:
        raise ValueError(f"Invalid continuation token: {exc}") from exc


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


async def serialize_task(
    db: AsyncSession,
    task: Any,
    *,
    message: str | None = None,
    file_diff: str | None = None,
    skill_bindings: list[str] | None = None,
) -> HandoffBundle:
    """Build a `HandoffBundle` from a running/paused Task + persisted steps."""
    meta = task.metadata or {}
    chat_id_str = meta.get("chat_id")
    project_id_str = meta.get("project_id")
    trajectory: list[dict] = []
    continuation: str | None = None

    if chat_id_str:
        try:
            chat_uuid = UUID(chat_id_str)
            rows = (
                await db.execute(
                    select(AgentStep)
                    .where(AgentStep.chat_id == chat_uuid)
                    .order_by(AgentStep.step_index.asc())
                )
            ).scalars().all()
            trajectory = [r.step_data for r in rows if r.step_data is not None]
            if rows:
                continuation = make_continuation_token(chat_id_str, int(rows[-1].step_index))
        except Exception:
            logger.debug("trajectory load failed for task=%s", task.id, exc_info=True)

    return HandoffBundle(
        task_id=str(task.id),
        project_id=str(project_id_str or ""),
        chat_id=str(chat_id_str or ""),
        message=message if message is not None else (meta.get("message") or ""),
        trajectory=trajectory,
        file_diff=file_diff,
        goal_ancestry=list(meta.get("goal_ancestry") or []),
        skill_bindings=list(skill_bindings or meta.get("skill_bindings") or []),
        continuation_token=continuation,
        agent_id=meta.get("agent_id"),
        container_name=meta.get("container_name"),
    )


# ---------------------------------------------------------------------------
# Deserialization — bundle → new task enqueue
# ---------------------------------------------------------------------------


def bundle_from_payload(payload: dict[str, Any]) -> HandoffBundle:
    if not payload.get("project_id") or not payload.get("chat_id"):
        raise ValueError("bundle requires project_id and chat_id")
    return HandoffBundle(
        project_id=str(payload["project_id"]),
        chat_id=str(payload["chat_id"]),
        message=str(payload.get("message") or ""),
        task_id=payload.get("task_id"),
        trajectory=list(payload.get("trajectory") or []),
        file_diff=payload.get("file_diff"),
        goal_ancestry=list(payload.get("goal_ancestry") or []),
        skill_bindings=list(payload.get("skill_bindings") or []),
        continuation_token=payload.get("continuation_token"),
        agent_id=payload.get("agent_id"),
        container_name=payload.get("container_name"),
    )


def build_enqueue_payload(
    bundle: HandoffBundle,
    *,
    user_id: UUID,
    project_slug: str,
    api_key_scopes: list[str] | None,
) -> tuple[str, dict[str, Any]]:
    """Return (task_id, AgentTaskPayload-compatible dict) ready for ARQ.

    Kept dict-based to avoid importing `AgentTaskPayload` at module top —
    tests that don't exercise the enqueue path should not have to stub it.
    """
    from ...services.agent_task import AgentTaskPayload

    task_id = str(uuid.uuid4())
    chat_history = [
        {"role": "assistant", "content": _step_summary(step)}
        for step in bundle.trajectory
        if _step_summary(step)
    ]
    payload = AgentTaskPayload(
        task_id=task_id,
        user_id=str(user_id),
        chat_id=bundle.chat_id,
        message=bundle.message,
        project_id=bundle.project_id,
        project_slug=project_slug,
        agent_id=bundle.agent_id,
        container_name=bundle.container_name,
        chat_history=chat_history,
        project_context={
            "handoff": {
                "origin_task_id": bundle.task_id,
                "continuation_token": bundle.continuation_token,
                "goal_ancestry": bundle.goal_ancestry,
                "skill_bindings": bundle.skill_bindings,
                "file_diff": bundle.file_diff,
            }
        },
        api_key_scopes=api_key_scopes,
    )
    return task_id, payload.to_dict()


def _step_summary(step: dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return ""
    return (
        step.get("response_text")
        or step.get("thought")
        or ""
    )


__all__ = [
    "HandoffBundle",
    "bundle_from_payload",
    "build_enqueue_payload",
    "make_continuation_token",
    "parse_continuation_token",
    "serialize_task",
]
