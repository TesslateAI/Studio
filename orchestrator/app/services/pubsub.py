"""
Redis Pub/Sub & Streams Service

Bridges Redis to local WebSocket connections for cross-pod communication.
- Pub/Sub: WebSocket status updates (fanout across pods)
- Redis Streams: Agent execution events (durable, replayable)
- Redis keys: Project locks (heartbeat-based), cancellation signals

Usage:
    from app.services.pubsub import get_pubsub

    pubsub = get_pubsub()
    if pubsub:
        await pubsub.publish_status_update(user_id, project_id, status)
        await pubsub.publish_agent_event(task_id, event)
"""

import asyncio
import contextlib
import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "tesslate:ws:"
AGENT_STREAM_PREFIX = "tesslate:agent:stream:"
PROJECT_LOCK_PREFIX = "tesslate:project:lock:"
CHAT_LOCK_PREFIX = "tesslate:chat:lock:"
CANCEL_KEY_PREFIX = "tesslate:agent:cancel:"

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


class RedisPubSub:
    """
    Redis Pub/Sub + Streams bridge for WebSocket fanout and agent events.

    - Pub/Sub: status updates to Redis channels keyed by user_id:project_id
    - Streams: agent events via XADD/XREAD for durability and replay
    - Keys: project locks with heartbeat TTL, cancellation signals
    """

    def __init__(self):
        self._subscriber_task: asyncio.Task | None = None
        self._running = False
        self._forward_tasks: dict[str, asyncio.Task] = {}

    # =========================================================================
    # WebSocket Status Updates (Pub/Sub - unchanged)
    # =========================================================================

    async def publish_status_update(self, user_id: UUID, project_id: UUID, status: dict):
        """
        Publish a status update to Redis for cross-pod delivery.

        Args:
            user_id: Target user
            project_id: Target project
            status: Status payload dict
        """
        from .cache_service import get_redis_client

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

    # =========================================================================
    # Agent Events (Redis Streams)
    # =========================================================================

    async def publish_agent_event(self, task_id: str, event: dict):
        """
        Publish an agent execution event to a Redis Stream.

        Uses XADD with MAXLEN ~500 to cap the stream size.
        On terminal events (done), sets a 1-hour expiry on the stream.

        Args:
            task_id: Unique agent task ID
            event: Agent event dict (type, data, etc.)
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        stream_key = f"{AGENT_STREAM_PREFIX}{task_id}"
        try:
            await redis.xadd(
                stream_key,
                {"data": json.dumps(event)},
                maxlen=500,
                approximate=True,
            )
            # Auto-expire stream after terminal event
            if event.get("type") == "done":
                await redis.expire(stream_key, 3600)
        except Exception as e:
            logger.warning(f"Failed to publish agent event to stream: {e}")

    async def subscribe_agent_events(self, task_id: str):
        """
        Subscribe to agent execution events for a specific task.

        Uses XREAD BLOCK to consume from the stream in real-time.
        Starts from beginning (0) to catch events published before subscribe.

        Args:
            task_id: Unique agent task ID

        Yields:
            dict: Agent event dicts
        """
        from .cache_service import get_redis_client

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
                    # BLOCK timeout, yield control and retry
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
        """
        Subscribe to agent events starting from a specific stream ID.

        For reconnection replay: first replays missed events via XRANGE,
        then tails live events via XREAD BLOCK.

        Args:
            task_id: Unique agent task ID
            last_id: Last seen stream entry ID (exclusive start for replay)

        Yields:
            dict: Agent event dicts
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        stream_key = f"{AGENT_STREAM_PREFIX}{task_id}"

        try:
            # Phase 1: Replay missed events via XRANGE (last_id, +]
            # XRANGE is inclusive on both ends, but we use the ID directly
            # since the caller's last_id is the last one they saw.
            # We use "(" prefix for exclusive start if supported,
            # but redis-py XRANGE doesn't support exclusive — so we filter.
            replay_entries = await redis.xrange(stream_key, min=last_id, max="+")
            current_last_id = last_id

            for entry_id, fields in replay_entries:
                # Skip the entry matching last_id (already seen)
                # With decode_responses=True, entry_id is a string
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

            # Phase 2: Live tail via XREAD BLOCK
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

    # =========================================================================
    # Project Locks (heartbeat-based)
    # =========================================================================

    async def acquire_project_lock(self, project_id: str, task_id: str) -> bool:
        """
        Acquire a per-project lock using SET NX EX 30.

        The lock is held by a specific task_id and must be extended
        via heartbeat (extend_project_lock) every <30 seconds.

        Args:
            project_id: Project to lock
            task_id: Task claiming the lock

        Returns:
            True if lock was acquired, False if already held by another task.
        """
        from .cache_service import get_redis_client

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
        """
        Extend a project lock TTL if we still hold it.

        Uses a Lua script to atomically check the value matches task_id
        before extending. Should be called every ~15 seconds as a heartbeat.

        Args:
            project_id: Project whose lock to extend
            task_id: Task that should be holding the lock

        Returns:
            True if lock was extended, False if we no longer hold it.
        """
        from .cache_service import get_redis_client

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
        """
        Release a project lock if we hold it.

        Uses a Lua script to atomically check the value matches task_id
        before deleting. Safe to call even if lock expired.

        Args:
            project_id: Project whose lock to release
            task_id: Task that should be holding the lock

        Returns:
            True if lock was released, False if we didn't hold it.
        """
        from .cache_service import get_redis_client

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
        """
        Get the task_id currently holding the project lock.

        Args:
            project_id: Project to check

        Returns:
            The task_id holding the lock, or None if unlocked.
        """
        from .cache_service import get_redis_client

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

    # =========================================================================
    # Chat Locks (per-session, heartbeat-based)
    # =========================================================================

    async def acquire_chat_lock(self, chat_id: str, task_id: str) -> bool:
        """
        Acquire a per-chat lock using SET NX EX 30.

        Allows concurrent agent execution across different chat sessions
        within the same project.

        Args:
            chat_id: Chat session to lock
            task_id: Task claiming the lock

        Returns:
            True if lock was acquired, False if already held by another task.
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CHAT_LOCK_PREFIX}{chat_id}"
        try:
            result = await redis.set(key, task_id, nx=True, ex=30)
            if result:
                logger.debug(f"Chat lock acquired: {chat_id} by {task_id}")
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to acquire chat lock: {e}")
            return False

    async def extend_chat_lock(self, chat_id: str, task_id: str) -> bool:
        """
        Extend a chat lock TTL if we still hold it.

        Args:
            chat_id: Chat session whose lock to extend
            task_id: Task that should be holding the lock

        Returns:
            True if lock was extended, False if we no longer hold it.
        """
        from .cache_service import get_redis_client

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
        """
        Release a chat lock if we hold it.

        Args:
            chat_id: Chat session whose lock to release
            task_id: Task that should be holding the lock

        Returns:
            True if lock was released, False if we didn't hold it.
        """
        from .cache_service import get_redis_client

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

    async def get_chat_lock(self, chat_id: str) -> str | None:
        """
        Get the task_id currently holding the chat lock.

        Args:
            chat_id: Chat session to check

        Returns:
            The task_id holding the lock, or None if unlocked.
        """
        from .cache_service import get_redis_client

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

    # =========================================================================
    # Cross-Source Visibility Bridge
    # =========================================================================

    async def publish_agent_task_notification(
        self, user_id: UUID, project_id: UUID, notification: dict
    ):
        """
        Publish an agent task notification via the existing WS Pub/Sub channel.

        Used to notify connected clients about agent task lifecycle events
        (started, completed, failed) so the UI can show real-time progress
        regardless of which pod is running the agent.

        Args:
            user_id: Target user
            project_id: Target project
            notification: Notification payload (should include 'type' field)
        """
        from .cache_service import get_redis_client

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
        """
        Subscribe to an agent's Redis Stream and forward events to local WebSocket.

        Spawned when an agent_task_started notification arrives via Pub/Sub.
        Reads from the agent stream and sends each event to the locally-connected
        WebSocket client, enabling cross-pod visibility of agent execution.

        Args:
            user_id: Target user
            project_id: Target project
            task_id: Agent task ID whose stream to follow
            chat_id: Chat session ID (for frontend filtering)
        """
        from ..routers.chat import manager

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
            # Clean up tracking
            self._forward_tasks.pop(task_id, None)

    # =========================================================================
    # Cancellation (Redis keys - unchanged)
    # =========================================================================

    async def request_cancellation(self, task_id: str):
        """
        Signal a worker to cancel an agent task.

        Sets a Redis key that the worker checks between iterations.
        Uses a key instead of Pub/Sub to avoid timing issues.
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        key = f"{CANCEL_KEY_PREFIX}{task_id}"
        try:
            await redis.setex(key, 600, "1")  # 10 min TTL
            logger.info(f"Cancellation requested for task {task_id}")
        except Exception as e:
            logger.warning(f"Failed to request cancellation: {e}")

    async def is_cancelled(self, task_id: str) -> bool:
        """
        Check if a task has been cancelled.

        Called by the worker between agent iterations.
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return False

        key = f"{CANCEL_KEY_PREFIX}{task_id}"
        try:
            return bool(await redis.exists(key))
        except Exception:
            return False

    # =========================================================================
    # Background Subscriber (Pub/Sub for WS + agent task bridging)
    # =========================================================================

    async def start_subscriber(self):
        """
        Start the background subscriber loop.

        Listens for Pub/Sub messages on tesslate:ws:* pattern and forwards
        them to locally-connected WebSocket clients.
        """
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            logger.info("Redis not available, skipping Pub/Sub subscriber")
            return

        self._running = True
        pubsub = redis.pubsub()

        try:
            # Pattern subscribe to all WebSocket channels
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
        """
        Handle an incoming Pub/Sub message by forwarding to local WebSocket.

        Also handles agent_task_started notifications by spawning a stream
        forwarder that bridges agent events to the local WebSocket.
        """
        try:
            data = json.loads(message["data"])
            msg_type = data.get("type", "")
            user_id = UUID(data["user_id"])
            project_id = UUID(data["project_id"])
            payload = data.get("payload", {})

            # Handle agent_task_started: bridge the agent stream to local WS
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

            # Default: forward status_update to local WebSocket
            from ..routers.chat import manager

            connection_key = (user_id, project_id)
            if connection_key in manager.active_connections:
                ws_message = json.dumps({"type": "status_update", "payload": payload})
                try:
                    await manager.active_connections[connection_key].send_text(ws_message)
                    logger.debug(f"Forwarded Pub/Sub message to local WebSocket: user={user_id}")
                except Exception as e:
                    logger.warning(f"Failed to forward to WebSocket: {e}")
                    # Clean up dead connection
                    manager.disconnect(user_id, project_id)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Invalid Pub/Sub message: {e}")

    async def stop(self):
        """Stop the subscriber loop and all forwarding tasks."""
        self._running = False

        # Cancel all active forwarding tasks
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


# =============================================================================
# Global Instance
# =============================================================================

_pubsub: RedisPubSub | None = None


def get_pubsub() -> RedisPubSub | None:
    """
    Get the global RedisPubSub instance.

    Returns None if Redis is not configured (single-pod mode).
    The instance is created lazily on first access.
    """
    global _pubsub
    if _pubsub is None:
        _pubsub = RedisPubSub()
    return _pubsub
