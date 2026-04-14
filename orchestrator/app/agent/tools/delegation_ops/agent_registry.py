"""
Subagent Registry

Per-process registry tracking delegated subagents spawned by the parent
agent during a single run. Records are addressable by `agent_id` and
carry status, conversation events, pending message queue, final response,
and an ATIF trajectory snapshot.

This module is the shared state backing for the delegation_ops tools
(task, wait_agent, send_message_to_agent, close_agent, list_agents).

All mutating operations are serialized via an ``asyncio.Lock`` so the
registry is safe to use from concurrent tool executors sharing the same
event loop. Background tasks spawned by the `task` tool are tracked here
so they can be cancelled cleanly on interpreter shutdown.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Hard cap on events buffered per subagent to avoid OOM on runaway loops.
MAX_BUFFERED_EVENTS = 10_000

# Hard cap on depth of nested delegation chains.
MAX_SUBAGENT_DEPTH = 3

# Valid status values — kept as plain strings so records can round-trip
# through ``json.dumps`` without custom encoders.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_TIMED_OUT = "timed_out"

TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_TIMED_OUT})


@dataclass
class SubagentRecord:
    """
    State for a single delegated subagent.

    Fields are intentionally flat and JSON-friendly except for ``task``,
    which is the raw ``asyncio.Task`` running the child agent's generator.
    ``task`` is excluded from serialization snapshots.
    """

    agent_id: str
    role: str
    status: str
    spawned_at: datetime
    task_text: str
    model_name: str
    depth: int
    parent_agent_id: str | None = None
    completed_at: datetime | None = None
    pending_messages: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    final_response: str | None = None
    trajectory: dict[str, Any] | None = None
    error: str | None = None
    task: asyncio.Task | None = None

    def snapshot(self) -> dict[str, Any]:
        """Serializable view for list_agents / wait_agent return values."""
        duration_ms: int | None = None
        if self.completed_at is not None:
            duration_ms = int((self.completed_at - self.spawned_at).total_seconds() * 1000)
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "status": self.status,
            "spawned_at": self.spawned_at.isoformat(),
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
            "depth": self.depth,
            "parent_agent_id": self.parent_agent_id,
            "model_name": self.model_name,
            "duration_ms": duration_ms,
            "event_count": len(self.events),
            "pending_message_count": len(self.pending_messages),
            "error": self.error,
        }


class SubagentRegistry:
    """Per-process async-safe registry of spawned subagents."""

    def __init__(self) -> None:
        self._records: dict[str, SubagentRecord] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Registration / lookup
    # ------------------------------------------------------------------

    async def register(self, record: SubagentRecord) -> None:
        async with self._lock:
            if record.agent_id in self._records:
                raise ValueError(f"Subagent {record.agent_id} already registered")
            self._records[record.agent_id] = record

    def get(self, agent_id: str) -> SubagentRecord | None:
        return self._records.get(agent_id)

    def list_all(self) -> list[SubagentRecord]:
        return list(self._records.values())

    def list_children_of(self, parent_agent_id: str) -> list[SubagentRecord]:
        return [rec for rec in self._records.values() if rec.parent_agent_id == parent_agent_id]

    def snapshot_for_listing(
        self,
        parent_agent_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for rec in self._records.values():
            if parent_agent_id is not None and rec.parent_agent_id != parent_agent_id:
                continue
            if status is not None and rec.status != status:
                continue
            snapshots.append(rec.snapshot())
        return snapshots

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    async def mark_running(self, agent_id: str) -> None:
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return
            if record.status == STATUS_PENDING:
                record.status = STATUS_RUNNING

    async def complete(
        self,
        agent_id: str,
        final_response: str | None,
        trajectory: dict[str, Any] | None,
    ) -> None:
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return
            if record.status in TERMINAL_STATUSES:
                return
            record.status = STATUS_COMPLETED
            record.final_response = final_response
            record.trajectory = trajectory
            record.completed_at = datetime.now(UTC)

    async def fail(self, agent_id: str, error: str) -> None:
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return
            if record.status in TERMINAL_STATUSES:
                return
            record.status = STATUS_FAILED
            record.error = error
            record.completed_at = datetime.now(UTC)

    async def mark_timed_out(self, agent_id: str) -> None:
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return
            if record.status in TERMINAL_STATUSES:
                return
            record.status = STATUS_TIMED_OUT
            record.error = record.error or "subagent exceeded timeout_ms"
            record.completed_at = datetime.now(UTC)

    async def cancel(self, agent_id: str) -> bool:
        """Cancel a running subagent. Idempotent — safe to call repeatedly."""
        task_to_cancel: asyncio.Task | None = None
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return False
            if record.status in TERMINAL_STATUSES:
                return True
            if record.task is not None and not record.task.done():
                task_to_cancel = record.task
            record.status = STATUS_CANCELLED
            if record.completed_at is None:
                record.completed_at = datetime.now(UTC)

        if task_to_cancel is not None:
            task_to_cancel.cancel()
        return True

    async def enqueue_message(self, agent_id: str, message: str) -> int:
        """Append a message to a running subagent's pending queue.

        Returns the new queue depth. Raises ``ValueError`` if the subagent
        is unknown or no longer running.
        """
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                raise ValueError(f"Unknown subagent: {agent_id}")
            if record.status not in (STATUS_PENDING, STATUS_RUNNING):
                raise ValueError(f"Subagent {agent_id} is not running (status={record.status})")
            record.pending_messages.append(message)
            return len(record.pending_messages)

    async def drain_messages(self, agent_id: str) -> list[str]:
        """Pop all pending messages for a subagent (used by the runner loop)."""
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return []
            if not record.pending_messages:
                return []
            messages = record.pending_messages
            record.pending_messages = []
            return messages

    async def append_event(self, agent_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return
            if len(record.events) >= MAX_BUFFERED_EVENTS:
                return
            record.events.append(event)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach_task(self, agent_id: str, task: asyncio.Task) -> None:
        record = self._records.get(agent_id)
        if record is not None:
            record.task = task

    async def shutdown(self) -> None:
        """Cancel every tracked task. Safe to call at interpreter exit."""
        for record in list(self._records.values()):
            if record.task is not None and not record.task.done():
                record.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await record.task

    def shutdown_sync(self) -> None:
        """Best-effort synchronous cancel used from ``atexit`` hooks."""
        for record in list(self._records.values()):
            task = record.task
            if task is not None and not task.done():
                try:
                    task.cancel()
                except Exception:
                    logger.debug("Failed to cancel subagent task %s", record.agent_id)

    def clear(self) -> None:
        """Remove all records (primarily for tests)."""
        self._records.clear()


# Module-level singleton consumed by the delegation tools.
SUBAGENT_REGISTRY = SubagentRegistry()


def _atexit_shutdown() -> None:
    try:
        SUBAGENT_REGISTRY.shutdown_sync()
    except Exception:  # pragma: no cover - defensive
        logger.debug("delegation registry shutdown hook failed", exc_info=True)


atexit.register(_atexit_shutdown)
