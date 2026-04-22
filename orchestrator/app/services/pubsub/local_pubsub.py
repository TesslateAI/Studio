"""
Local in-process PubSub implementation.

For the desktop sidecar (single-process, no Redis). Uses asyncio primitives:
- Each agent task stream is an append-only list keyed by task_id.
- Consumer groups are tracked as {stream: {group: {consumer: last_index}}}.
- Subscribers poll the list via an asyncio.Event per stream.
- Locks are in-process dicts with monotonic TTLs.
- Status updates and task notifications fan out to locally-registered WS
  clients directly (no cross-pod bridge is needed in single-process mode).

Semantics match the Redis backend's observable behavior:
- subscribe_agent_events starts from index 0 and replays.
- subscribe_agent_events_from(last_id) replays entries after last_id and tails
  newly-appended ones.
- "done" events terminate the subscription.
- last_id is a zero-padded numeric string so it compares lexically.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from uuid import UUID

logger = logging.getLogger(__name__)


def _fmt_id(idx: int) -> str:
    # 0-padded so lexicographic ordering tracks numeric ordering
    return f"{idx:020d}"


def _parse_id(last_id: str) -> int:
    try:
        return int(last_id)
    except (TypeError, ValueError):
        return -1


class _Stream:
    __slots__ = ("entries", "event", "closed")

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict]] = []
        self.event: asyncio.Event = asyncio.Event()
        self.closed: bool = False

    def append(self, event: dict) -> str:
        entry_id = _fmt_id(len(self.entries))
        self.entries.append((entry_id, event))
        self.event.set()
        return entry_id

    def wake(self) -> None:
        self.event.set()


class LocalPubSub:
    """Single-process pub/sub backend. No Redis required."""

    def __init__(self) -> None:
        self._streams: dict[str, _Stream] = {}
        # groups[stream_key][group][consumer] = last_index_seen
        self._groups: dict[str, dict[str, dict[str, int]]] = {}
        # project/chat locks: {key: (holder_task_id, expires_at_monotonic)}
        self._project_locks: dict[str, tuple[str, float]] = {}
        self._chat_locks: dict[str, tuple[str, float]] = {}
        # cancellations: {task_id: expires_at_monotonic}
        self._cancellations: dict[str, float] = {}
        self._running = False
        # Local status subscribers: (user_id, project_id) -> list[asyncio.Queue]
        self._status_subscribers: dict[tuple[UUID, UUID], list[asyncio.Queue]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_stream(self, task_id: str) -> _Stream:
        s = self._streams.get(task_id)
        if s is None:
            s = _Stream()
            self._streams[task_id] = s
        return s

    def _lock_alive(self, entry: tuple[str, float] | None) -> bool:
        return entry is not None and entry[1] > time.monotonic()

    # ------------------------------------------------------------------
    # Status / notification fanout (local only)
    # ------------------------------------------------------------------
    async def publish_status_update(self, user_id: UUID, project_id: UUID, status: dict) -> None:
        await self._fanout_local(user_id, project_id, {"type": "status_update", "payload": status})

    async def publish_agent_task_notification(
        self, user_id: UUID, project_id: UUID, notification: dict
    ) -> None:
        await self._fanout_local(
            user_id,
            project_id,
            {"type": notification.get("type", "agent_task_notification"), "payload": notification},
        )

    async def _fanout_local(self, user_id: UUID, project_id: UUID, message: dict) -> None:
        subs = self._status_subscribers.get((user_id, project_id))
        if not subs:
            return
        payload = json.dumps(message)
        for q in list(subs):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Local status subscriber queue full; dropping message")

    def register_status_subscriber(
        self, user_id: UUID, project_id: UUID, queue: asyncio.Queue
    ) -> None:
        self._status_subscribers.setdefault((user_id, project_id), []).append(queue)

    def unregister_status_subscriber(
        self, user_id: UUID, project_id: UUID, queue: asyncio.Queue
    ) -> None:
        subs = self._status_subscribers.get((user_id, project_id))
        if not subs:
            return
        with contextlib.suppress(ValueError):
            subs.remove(queue)
        if not subs:
            self._status_subscribers.pop((user_id, project_id), None)

    # ------------------------------------------------------------------
    # Agent event streams
    # ------------------------------------------------------------------
    async def publish_agent_event(self, task_id: str, event: dict) -> None:
        self._get_stream(task_id).append(event)

    async def subscribe_agent_events(self, task_id: str):
        async for event in self._tail_from_index(task_id, start_index=0):
            yield event

    async def subscribe_agent_events_from(self, task_id: str, last_id: str):
        start = _parse_id(last_id) + 1
        if start < 0:
            start = 0
        async for event in self._tail_from_index(task_id, start_index=start):
            yield event

    async def _tail_from_index(self, task_id: str, start_index: int):
        stream = self._get_stream(task_id)
        idx = start_index
        try:
            while True:
                while idx < len(stream.entries):
                    _entry_id, event = stream.entries[idx]
                    idx += 1
                    yield event
                    if event.get("type") == "done":
                        return
                # No new entries; wait to be woken
                stream.event.clear()
                try:
                    await asyncio.wait_for(stream.event.wait(), timeout=1.0)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------
    # Consumer-group API (used by tests + future local multi-consumer use)
    # ------------------------------------------------------------------
    async def group_read(
        self, task_id: str, group: str, consumer: str, count: int = 100
    ) -> list[tuple[str, dict]]:
        stream = self._get_stream(task_id)
        groups = self._groups.setdefault(task_id, {}).setdefault(group, {})
        last = groups.get(consumer, -1)

        # Figure out the group-wide high-water mark so multiple consumers
        # in the same group see disjoint subsets.
        group_hw = max(groups.values(), default=-1)
        start = max(last, group_hw) + 1

        out: list[tuple[str, dict]] = []
        for i in range(start, min(start + count, len(stream.entries))):
            entry_id, event = stream.entries[i]
            out.append((entry_id, event))
            groups[consumer] = i
        return out

    async def group_ack(self, task_id: str, group: str, consumer: str, last_id: str) -> None:
        idx = _parse_id(last_id)
        groups = self._groups.setdefault(task_id, {}).setdefault(group, {})
        groups[consumer] = max(groups.get(consumer, -1), idx)

    async def group_resume_from(
        self, task_id: str, group: str, consumer: str
    ) -> list[tuple[str, dict]]:
        """Replay everything after this consumer's last_id (reconnect path)."""
        stream = self._get_stream(task_id)
        groups = self._groups.setdefault(task_id, {}).setdefault(group, {})
        last = groups.get(consumer, -1)
        return list(stream.entries[last + 1 :])

    # ------------------------------------------------------------------
    # Locks (project + chat)
    # ------------------------------------------------------------------
    def _acquire(
        self, table: dict[str, tuple[str, float]], key: str, task_id: str, ttl: float = 30.0
    ) -> bool:
        current = table.get(key)
        if self._lock_alive(current):
            return False
        table[key] = (task_id, time.monotonic() + ttl)
        return True

    def _extend(
        self, table: dict[str, tuple[str, float]], key: str, task_id: str, ttl: float = 30.0
    ) -> bool:
        current = table.get(key)
        if not self._lock_alive(current) or current[0] != task_id:
            return False
        table[key] = (task_id, time.monotonic() + ttl)
        return True

    def _release(self, table: dict[str, tuple[str, float]], key: str, task_id: str) -> bool:
        current = table.get(key)
        if current and current[0] == task_id:
            table.pop(key, None)
            return True
        return False

    def _get_holder(self, table: dict[str, tuple[str, float]], key: str) -> str | None:
        current = table.get(key)
        if self._lock_alive(current):
            return current[0]
        if current is not None:
            # expired — clean up
            table.pop(key, None)
        return None

    async def acquire_project_lock(self, project_id: str, task_id: str) -> bool:
        return self._acquire(self._project_locks, project_id, task_id)

    async def extend_project_lock(self, project_id: str, task_id: str) -> bool:
        return self._extend(self._project_locks, project_id, task_id)

    async def release_project_lock(self, project_id: str, task_id: str) -> bool:
        return self._release(self._project_locks, project_id, task_id)

    async def get_project_lock(self, project_id: str) -> str | None:
        return self._get_holder(self._project_locks, project_id)

    async def acquire_chat_lock(self, chat_id: str, task_id: str) -> bool:
        """Acquire or take over a chat lock (desktop parity with Redis backend).

        Takes over the lock if the current holder has been cancelled.
        """
        current = self._chat_locks.get(chat_id)
        if not self._lock_alive(current):
            self._chat_locks[chat_id] = (task_id, time.monotonic() + 30.0)
            return True
        if current[0] == task_id:
            self._chat_locks[chat_id] = (task_id, time.monotonic() + 30.0)
            return True
        # Takeover if current holder has been flagged cancelled.
        if await self.is_cancelled(current[0]):
            logger.info(f"Chat lock taken over from cancelled zombie: {chat_id} by {task_id}")
            self._chat_locks[chat_id] = (task_id, time.monotonic() + 30.0)
            return True
        return False

    async def extend_chat_lock(self, chat_id: str, task_id: str) -> bool:
        return self._extend(self._chat_locks, chat_id, task_id)

    async def release_chat_lock(self, chat_id: str, task_id: str) -> bool:
        return self._release(self._chat_locks, chat_id, task_id)

    async def force_release_chat_lock(self, chat_id: str) -> bool:
        current = self._chat_locks.get(chat_id)
        if current is None:
            return False
        holder_task = current[0]
        await self.request_cancellation(holder_task)
        self._chat_locks.pop(chat_id, None)
        return True

    async def get_chat_lock(self, chat_id: str) -> str | None:
        return self._get_holder(self._chat_locks, chat_id)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------
    async def request_cancellation(self, task_id: str) -> None:
        self._cancellations[task_id] = time.monotonic() + 600.0

    async def is_cancelled(self, task_id: str) -> bool:
        exp = self._cancellations.get(task_id)
        if exp is None:
            return False
        if exp <= time.monotonic():
            self._cancellations.pop(task_id, None)
            return False
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start_subscriber(self) -> None:
        # No cross-pod bridge needed in single-process mode.
        self._running = True
        logger.info("LocalPubSub started (in-proc, no Redis)")

    async def stop(self) -> None:
        self._running = False
        for stream in self._streams.values():
            stream.wake()
        logger.info("LocalPubSub stopped")


__all__ = ["LocalPubSub"]
