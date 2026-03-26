"""
Non-blocking incremental trajectory writer.

Writes ATIF v1.4 JSON files to the project volume via the orchestrator
abstraction layer (get_orchestrator().write_file()). This ensures
identical behavior on Docker (direct filesystem at /projects/{slug}/)
and Kubernetes (kubectl exec into file-manager pod).

All writes are wrapped in try/except — trajectory I/O failures never
crash or block the agent.
"""

import json
import logging
from datetime import UTC
from typing import Any

from .trajectory import TrajectoryRecorder, convert_to_atif

logger = logging.getLogger(__name__)


class TrajectoryWriter:
    """Flush trajectory data to .tesslate/trajectories/ inside the project volume."""

    def __init__(self, context: dict[str, Any], session_id: str):
        self.user_id = context.get("user_id")
        self.project_id = context.get("project_id")
        self.project_slug = context.get("project_slug")
        self.container_name = context.get("container_name")
        self.container_directory = context.get("container_directory")
        self.session_id = session_id

    async def flush(self, recorder: TrajectoryRecorder) -> None:
        """Write main ATIF JSON to the project volume.

        Called after each significant recording event for incremental persistence.
        """
        try:
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            atif = recorder.to_atif()
            content = json.dumps(atif, indent=2, default=str)

            await orchestrator.write_file(
                user_id=self.user_id,
                project_id=self.project_id,
                container_name=self.container_name,
                file_path=f".tesslate/trajectories/trajectory_{self.session_id}.json",
                content=content,
                project_slug=self.project_slug,
                subdir=self.container_directory,
            )
        except Exception as e:
            logger.debug(f"[TrajectoryWriter] Flush failed (non-fatal): {e}")

    async def save_subagent_trajectory(
        self,
        subagent_type: str,
        index: int,
        agent_id: str,
        messages: list[dict[str, Any]],
        model_name: str,
    ) -> None:
        """Convert a subagent session to ATIF and save as a separate file.

        Output: .tesslate/trajectories/trajectory_{type}_{index}.json
        """
        try:
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            atif = convert_to_atif(
                trajectory=_messages_to_trajectory(messages),
                session_id=f"{self.session_id}-{subagent_type}-{index}",
                model_name=model_name,
                agent_name=f"tesslate-agent-{subagent_type}",
            )
            atif["subagent"] = {
                "type": subagent_type,
                "index": index,
                "agent_id": agent_id,
            }

            content = json.dumps(atif, indent=2, default=str)

            await orchestrator.write_file(
                user_id=self.user_id,
                project_id=self.project_id,
                container_name=self.container_name,
                file_path=f".tesslate/trajectories/trajectory_{subagent_type}_{index}.json",
                content=content,
                project_slug=self.project_slug,
                subdir=self.container_directory,
            )
            logger.debug(f"[TrajectoryWriter] Saved subagent trajectory: {subagent_type}_{index}")
        except Exception as e:
            logger.debug(f"[TrajectoryWriter] Subagent save failed (non-fatal): {e}")

    async def mirror_plan(self, plan_markdown: str, plan_name: str) -> None:
        """Save plan markdown to .tesslate/trajectories/plans/{plan_name}.md"""
        try:
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            await orchestrator.write_file(
                user_id=self.user_id,
                project_id=self.project_id,
                container_name=self.container_name,
                file_path=f".tesslate/trajectories/plans/{plan_name}.md",
                content=plan_markdown,
                project_slug=self.project_slug,
                subdir=self.container_directory,
            )
            logger.debug(f"[TrajectoryWriter] Mirrored plan: {plan_name}")
        except Exception as e:
            logger.debug(f"[TrajectoryWriter] Plan mirror failed (non-fatal): {e}")


def _messages_to_trajectory(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-format messages to trajectory entries.

    Subagent sessions store messages in OpenAI format (role, content, tool_calls).
    We convert them to the trajectory entry format expected by convert_to_atif().
    """
    from datetime import datetime

    entries = []
    now = datetime.now(UTC).isoformat()

    for msg in messages:
        role = msg.get("role", "")
        entry: dict[str, Any] = {
            "role": role,
            "content": msg.get("content")
            if isinstance(msg.get("content"), str)
            else str(msg.get("content") or ""),
            "timestamp": now,
        }
        if role == "assistant" and msg.get("tool_calls"):
            entry["tool_calls"] = msg["tool_calls"]
        if role == "tool" and msg.get("tool_call_id"):
            entry["tool_call_id"] = msg["tool_call_id"]
        entries.append(entry)

    return entries
