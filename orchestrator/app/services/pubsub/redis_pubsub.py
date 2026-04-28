"""
Redis Pub/Sub & Streams Service

Bridges Redis to local WebSocket connections for cross-pod communication.
- Pub/Sub: WebSocket status updates (fanout across pods)
- Redis Streams: Agent execution events (durable, replayable)
- Redis keys: Project locks (heartbeat-based), cancellation signals
"""

import asyncio
import contextlib
import json
import logging
from uuid import UUID

from .base import (
    AGENT_STREAM_PREFIX,
    APP_RUNTIME_STREAM_PREFIX,
    CANCEL_KEY_PREFIX,
    CHANNEL_PREFIX,
    CHAT_LOCK_PREFIX,
    PROJECT_LOCK_PREFIX,
)

logger = logging.getLogger(__name__)


def APP_RUNTIME_STREAM_KEY(app_instance_id) -> str:  # noqa: N802
    """Redis Stream key for app-instance runtime events."""
    return f"{APP_RUNTIME_STREAM_PREFIX}{app_instance_id}"


async def publish_app_runtime_event(app_instance_id, payload: dict) -> None:
    """Publish an app-runtime lifecycle event to its Redis Stream.

    Best-effort: swallows all errors so the pod-lifecycle caller is never
    blocked by Redis hiccups. Uses XADD with MAXLEN ~ 1000 to cap stream size.
    """
    from .cache_service import get_redis_client

    try:
        redis = await get_redis_client()
        if not redis:
            return
        stream_key = APP_RUNTIME_STREAM_KEY(app_instance_id)
        await redis.xadd(
            stream_key,
            {"data": json.dumps(payload)},
            maxlen=1000,
            approximate=True,
        )
        # Auto-expire after terminal state to avoid leaking keys
        if payload.get("state") in ("running", "error", "stopped"):
            with contextlib.suppress(Exception):
                await redis.expire(stream_key, 3600)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"publish_app_runtime_event ignored error: {e}")


async def subscribe_app_runtime_events(app_instance_id, *, last_id: str = "$"):
    """Subscribe to app-runtime events for an app instance.

    Yields ``(event_id, payload_dict)`` tuples. Defaults to ``$`` (only new
    events from subscribe time forward); pass ``"0"`` to replay history.
    """
    from .cache_service import get_redis_client

    redis = await get_redis_client()
    if not redis:
        return

    stream_key = APP_RUNTIME_STREAM_KEY(app_instance_id)
    cur = last_id
    try:
        while True:
            results = await redis.xread({stream_key: cur}, block=1000, count=100)
            if not results:
                await asyncio.sleep(0.01)
                continue
            for _stream, entries in results:
                for entry_id, fields in entries:
                    cur = entry_id
                    try:
                        event = json.loads(fields.get("data") or fields.get(b"data"))
                        yield entry_id, event
                    except (json.JSONDecodeError, KeyError, TypeError):
                        logger.warning(f"Invalid data in app_runtime stream entry: {entry_id}")
    except asyncio.CancelledError:
        logger.debug(f"App runtime subscription cancelled: {stream_key}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"App runtime subscription error: {e}")


# Lua script: extend lock only if we hold it
_EXTEND_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    redis.call('expire', KEYS[1], 30)
    return 1
end
return 0
"""

# Lua script: release lock only if we hold it
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    redis.call('del', KEYS[1])
    return 1
end
return 0
"""

# Lua script: acquire chat lock with takeover from cancelled holders.
#
# KEYS[1] = chat lock key (tesslate:chat:lock:{chat_id})
# ARGV[1] = new task_id
# ARGV[2] = ttl seconds
# ARGV[3] = cancel key prefix (tesslate:agent:cancel:)
#
# Returns:
#   1 — acquired (no prior holder)
#   2 — took over a cancelled zombie holder
#   0 — blocked by a live holder
_ACQUIRE_OR_TAKEOVER_SCRIPT = """
local current = redis.call('get', KEYS[1])
if not current then
    redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
    return 1
end
if current == ARGV[1] then
    redis.call('expire', KEYS[1], ARGV[2])
    return 1
end
local cancel_key = ARGV[3] .. current
if redis.call('exists', cancel_key) == 1 then
    redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
    return 2
end
return 0
"""


class RedisPubSub:
    """
    Redis Pub/Sub + Streams bridge for WebSocket fanout and agent events.
    """

    def __init__(self):
        self._subscriber_task: asyncio.Task | None = None
        self._running = False
        self._forward_tasks: dict[str, asyncio.Task] = {}

    async def publish_status_update(self, user_id: UUID, project_id: UUID, status: dict):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        channel = f"{CHANNEL_PREFIX}{user_id}:{project_id}"
        message = json.dumps(
            {
                "type": "status_update",
                "user_id": str(user_id),
                "project_id": str(project_id),
                "payload": status,
            }
        )

        try:
            await redis.publish(channel, message)
            logger.debug(f"Published status update to {channel}")
        except Exception as e:
            logger.warning(f"Failed to publish status update: {e}")

    async def publish_agent_event(self, task_id: str, event: dict):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        stream_key = f"{AGENT_STREAM_PREFIX}{task_id}"
        try:
            await redis.xadd(
                stream_key,
                {"data": json.dumps(event)},
                maxlen=5000,
                approximate=True,
            )
            if event.get("type") == "done":
                await redis.expire(stream_key, 3600)
        except Exception as e:
            logger.warning(f"Failed to publish agent event to stream: {e}")

    async def subscribe_agent_events(self, task_id: str):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        stream_key = f"{AGENT_STREAM_PREFIX}{task_id}"
        last_id = "0"

        try:
            logger.debug(f"Subscribed to agent stream: {stream_key}")

            while True:
                results = await redis.xread({stream_key: last_id}, block=1000, count=100)
                if not results:
                    await asyncio.sleep(0.01)
                    continue

                for _stream_name, entries in results:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        try:
                            event = json.loads(fields.get("data") or fields.get(b"data"))
                            yield event
                            if event.get("type") == "done":
                                return
                        except (json.JSONDecodeError, KeyError, TypeError):
                            logger.warning(f"Invalid data in agent stream entry: {entry_id}")

        except asyncio.CancelledError:
            logger.debug(f"Agent stream subscription cancelled: {stream_key}")
        except Exception as e:
            logger.warning(f"Agent stream subscription error: {e}")

    async def subscribe_agent_events_from(self, task_id: str, last_id: str):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        stream_key = f"{AGENT_STREAM_PREFIX}{task_id}"

        try:
            replay_entries = await redis.xrange(stream_key, min=last_id, max="+")
            current_last_id = last_id

            for entry_id, fields in replay_entries:
                comparable_last_id = last_id if isinstance(entry_id, str) else last_id.encode()
                if entry_id == comparable_last_id:
                    continue
                current_last_id = entry_id
                try:
                    event = json.loads(fields.get("data") or fields.get(b"data"))
                    yield event
                    if event.get("type") in ("complete", "error", "done"):
                        return
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning(f"Invalid data in agent stream replay entry: {entry_id}")

            while True:
                results = await redis.xread({stream_key: current_last_id}, block=1000, count=100)
                if not results:
                    await asyncio.sleep(0.01)
                    continue

                for _stream_name, entries in results:
                    for entry_id, fields in entries:
                        current_last_id = entry_id
                        try:
                            event = json.loads(fields.get("data") or fields.get(b"data"))
                            yield event
                            if event.get("type") == "done":
                                return
                        except (json.JSONDecodeError, KeyError, TypeError):
                            logger.warning(f"Invalid data in agent stream entry: {entry_id}")

        except asyncio.CancelledError:
            logger.debug(f"Agent stream subscription (from {last_id}) cancelled: {stream_key}")
        except Exception as e:
            logger.warning(f"Agent stream subscription (from {last_id}) error: {e}")

    async def acquire_project_lock(self, project_id: str, task_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{PROJECT_LOCK_PREFIX}{project_id}"
        try:
            result = await redis.set(key, task_id, nx=True, ex=30)
            if result:
                logger.debug(f"Project lock acquired: {project_id} by {task_id}")
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to acquire project lock: {e}")
            return False

    async def extend_project_lock(self, project_id: str, task_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{PROJECT_LOCK_PREFIX}{project_id}"
        try:
            result = await redis.eval(_EXTEND_LOCK_SCRIPT, 1, key, task_id)
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to extend project lock: {e}")
            return False

    async def release_project_lock(self, project_id: str, task_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{PROJECT_LOCK_PREFIX}{project_id}"
        try:
            result = await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, task_id)
            if result:
                logger.debug(f"Project lock released: {project_id} by {task_id}")
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to release project lock: {e}")
            return False

    async def get_project_lock(self, project_id: str) -> str | None:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return None

        key = f"{PROJECT_LOCK_PREFIX}{project_id}"
        try:
            value = await redis.get(key)
            if value is not None:
                return value.decode() if isinstance(value, bytes) else value
            return None
        except Exception as e:
            logger.warning(f"Failed to get project lock: {e}")
            return None

    async def acquire_chat_lock(self, chat_id: str, task_id: str) -> bool:
        """Acquire or take over a chat lock.

        Returns True if we now own the lock — either because it was free or
        because the prior holder was flagged cancelled (zombie takeover).
        Returns False only if a LIVE (non-cancelled) task holds the lock.
        """
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CHAT_LOCK_PREFIX}{chat_id}"
        try:
            result = await redis.eval(
                _ACQUIRE_OR_TAKEOVER_SCRIPT,
                1,
                key,
                task_id,
                30,
                CANCEL_KEY_PREFIX,
            )
            code = int(result) if result is not None else 0
            if code == 2:
                logger.info(f"Chat lock taken over from cancelled zombie: {chat_id} by {task_id}")
            elif code == 1:
                logger.debug(f"Chat lock acquired: {chat_id} by {task_id}")
            return code > 0
        except Exception as e:
            logger.warning(f"Failed to acquire chat lock: {e}")
            return False

    async def extend_chat_lock(self, chat_id: str, task_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CHAT_LOCK_PREFIX}{chat_id}"
        try:
            result = await redis.eval(_EXTEND_LOCK_SCRIPT, 1, key, task_id)
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to extend chat lock: {e}")
            return False

    async def release_chat_lock(self, chat_id: str, task_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CHAT_LOCK_PREFIX}{chat_id}"
        try:
            result = await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, task_id)
            if result:
                logger.debug(f"Chat lock released: {chat_id} by {task_id}")
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to release chat lock: {e}")
            return False

    async def force_release_chat_lock(self, chat_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CHAT_LOCK_PREFIX}{chat_id}"
        try:
            holding_task = await redis.get(key)
            if holding_task:
                task_id = holding_task.decode() if isinstance(holding_task, bytes) else holding_task
                await self.request_cancellation(task_id)
            deleted = await redis.delete(key)
            if deleted:
                logger.info(f"Force-released chat lock: {chat_id}")
            return bool(deleted)
        except Exception as e:
            logger.warning(f"Failed to force-release chat lock: {e}")
            return False

    async def get_chat_lock(self, chat_id: str) -> str | None:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return None

        key = f"{CHAT_LOCK_PREFIX}{chat_id}"
        try:
            value = await redis.get(key)
            if value is not None:
                return value.decode() if isinstance(value, bytes) else value
            return None
        except Exception as e:
            logger.warning(f"Failed to get chat lock: {e}")
            return None

    async def publish_agent_task_notification(
        self, user_id: UUID, project_id: UUID, notification: dict
    ):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        channel = f"{CHANNEL_PREFIX}{user_id}:{project_id}"
        message = json.dumps(
            {
                "type": notification.get("type", "agent_task_notification"),
                "user_id": str(user_id),
                "project_id": str(project_id),
                "payload": notification,
            }
        )

        try:
            await redis.publish(channel, message)
            logger.debug(
                f"Published agent task notification to {channel}: {notification.get('type')}"
            )
        except Exception as e:
            logger.warning(f"Failed to publish agent task notification: {e}")

    async def _forward_agent_events_to_ws(
        self, user_id: UUID, project_id: UUID, task_id: str, chat_id: str | None = None
    ):
        from ...routers.chat import manager

        connection_key = (user_id, project_id)

        try:
            async for event in self.subscribe_agent_events(task_id):
                if connection_key not in manager.active_connections:
                    logger.debug(
                        f"WebSocket disconnected, stopping agent event forwarding: "
                        f"user={user_id} task={task_id}"
                    )
                    break

                msg = {"type": "agent_event", "task_id": task_id, "payload": event}
                if chat_id:
                    msg["chat_id"] = chat_id
                ws_message = json.dumps(msg)
                try:
                    await manager.active_connections[connection_key].send_text(ws_message)
                except Exception as e:
                    logger.warning(f"Failed to forward agent event to WebSocket: {e}")
                    manager.disconnect(user_id, project_id)
                    break
        except Exception as e:
            logger.warning(f"Agent event forwarding error for task {task_id}: {e}")
        finally:
            self._forward_tasks.pop(task_id, None)

    async def request_cancellation(self, task_id: str):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        key = f"{CANCEL_KEY_PREFIX}{task_id}"
        try:
            await redis.setex(key, 600, "1")
            logger.info(f"Cancellation requested for task {task_id}")
        except Exception as e:
            logger.warning(f"Failed to request cancellation: {e}")

    async def is_cancelled(self, task_id: str) -> bool:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CANCEL_KEY_PREFIX}{task_id}"
        try:
            return bool(await redis.exists(key))
        except Exception:
            return False

    async def start_subscriber(self):
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            logger.info("Redis not available, skipping Pub/Sub subscriber")
            return

        self._running = True
        pubsub = redis.pubsub()

        try:
            await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
            logger.info("Redis Pub/Sub subscriber started (pattern: tesslate:ws:*)")

            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "pmessage":
                    await self._handle_pubsub_message(message)
                else:
                    await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info("Redis Pub/Sub subscriber cancelled")
        except Exception as e:
            logger.error(f"Redis Pub/Sub subscriber error: {e}", exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.punsubscribe(f"{CHANNEL_PREFIX}*")
                await pubsub.close()
            self._running = False

    async def _handle_pubsub_message(self, message: dict):
        try:
            data = json.loads(message["data"])
            msg_type = data.get("type", "")
            user_id = UUID(data["user_id"])
            project_id = UUID(data["project_id"])
            payload = data.get("payload", {})

            if msg_type == "agent_task_started":
                task_id = payload.get("task_id")
                chat_id = payload.get("chat_id")
                if task_id and task_id not in self._forward_tasks:
                    task = asyncio.create_task(
                        self._forward_agent_events_to_ws(
                            user_id, project_id, task_id, chat_id=chat_id
                        )
                    )
                    self._forward_tasks[task_id] = task
                    logger.debug(f"Spawned agent event forwarder for task {task_id}")
                return

            from ...routers.chat import manager

            connection_key = (user_id, project_id)
            if connection_key in manager.active_connections:
                ws_message = json.dumps({"type": "status_update", "payload": payload})
                try:
                    await manager.active_connections[connection_key].send_text(ws_message)
                    logger.debug(f"Forwarded Pub/Sub message to local WebSocket: user={user_id}")
                except Exception as e:
                    logger.warning(f"Failed to forward to WebSocket: {e}")
                    manager.disconnect(user_id, project_id)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Invalid Pub/Sub message: {e}")

    async def stop(self):
        self._running = False

        for _task_id, task in list(self._forward_tasks.items()):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._forward_tasks.clear()

        if self._subscriber_task and not self._subscriber_task.done():
            self._subscriber_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._subscriber_task


__all__ = ["RedisPubSub"]
