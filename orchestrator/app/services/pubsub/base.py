"""
PubSub Protocol — the surface all pub/sub backends must implement.

This captures what callers actually use from `get_pubsub()` today, inferred
by auditing every `from .pubsub import get_pubsub` / `.services.pubsub` site.

Two backends satisfy this protocol:
- RedisPubSub (cloud): Redis Pub/Sub + Streams + Lua-scripted locks
- LocalPubSub (desktop): in-proc asyncio.Queue fanout + consumer groups

Methods are documented where behavior semantics matter across backends.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class PubSub(Protocol):
    # WebSocket status fanout
    async def publish_status_update(
        self, user_id: UUID, project_id: UUID, status: dict
    ) -> None: ...

    async def publish_agent_task_notification(
        self, user_id: UUID, project_id: UUID, notification: dict
    ) -> None: ...

    # Agent event streams (durable, replayable)
    async def publish_agent_event(self, task_id: str, event: dict) -> None: ...

    def subscribe_agent_events(self, task_id: str) -> AsyncIterator[dict]: ...

    def subscribe_agent_events_from(self, task_id: str, last_id: str) -> AsyncIterator[dict]: ...

    # Project locks
    async def acquire_project_lock(self, project_id: str, task_id: str) -> bool: ...
    async def extend_project_lock(self, project_id: str, task_id: str) -> bool: ...
    async def release_project_lock(self, project_id: str, task_id: str) -> bool: ...
    async def get_project_lock(self, project_id: str) -> str | None: ...

    # Chat locks
    async def acquire_chat_lock(self, chat_id: str, task_id: str) -> bool: ...
    async def extend_chat_lock(self, chat_id: str, task_id: str) -> bool: ...
    async def release_chat_lock(self, chat_id: str, task_id: str) -> bool: ...
    async def force_release_chat_lock(self, chat_id: str) -> bool: ...
    async def get_chat_lock(self, chat_id: str) -> str | None: ...

    # Cancellation signals
    async def request_cancellation(self, task_id: str) -> None: ...
    async def is_cancelled(self, task_id: str) -> bool: ...

    # Lifecycle
    async def start_subscriber(self) -> None: ...
    async def stop(self) -> None: ...


# Re-exported constants (previously module-level in the monolithic pubsub.py).
CHANNEL_PREFIX = "tesslate:ws:"
AGENT_STREAM_PREFIX = "tesslate:agent:stream:"
APP_RUNTIME_STREAM_PREFIX = "tesslate:app_runtime:"
PROJECT_LOCK_PREFIX = "tesslate:project:lock:"
CHAT_LOCK_PREFIX = "tesslate:chat:lock:"
CANCEL_KEY_PREFIX = "tesslate:agent:cancel:"


__all__ = [
    "PubSub",
    "CHANNEL_PREFIX",
    "AGENT_STREAM_PREFIX",
    "APP_RUNTIME_STREAM_PREFIX",
    "PROJECT_LOCK_PREFIX",
    "CHAT_LOCK_PREFIX",
    "CANCEL_KEY_PREFIX",
]


# Silence "imported but unused" for Any (kept for downstream type hints).
_ = Any
