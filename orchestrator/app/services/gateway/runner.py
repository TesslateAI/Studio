"""
Gateway Runner — manages persistent platform connections, routes inbound
messages to the agent system, and delivers responses back to users.

One runner per shard. Uses K8s Recreate strategy (replicas=1) + file lock
as defense-in-depth for Docker Compose.
"""

import asyncio
import contextlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_PENDING_SENTINEL = object()
_RECONNECT_BACKOFF_BASE = 30  # seconds
_RECONNECT_BACKOFF_CAP = 300  # 5 minutes
_RECONNECT_MAX_ATTEMPTS = 20


class GatewayRunner:
    """Unified messaging gateway process."""

    def __init__(self, shard: int = 0):
        self.shard = shard
        self.adapters: dict[str, Any] = {}  # config_id → GatewayAdapter
        self._active_sessions: dict[str, Any] = {}  # session_key → task_id or sentinel
        self._pending_messages: dict[str, list] = {}  # session_key → queued msgs
        self._failed_adapters: dict[str, int] = {}  # config_id → retry count
        self._failed_timestamps: dict[str, float] = {}  # config_id → last failure time
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._background_tasks: set[asyncio.Task] = set()
        self._redis = None
        self._arq_pool = None
        self._db_factory = None

    async def start(self, db_factory, redis, arq_pool) -> None:
        """
        Main entry point. Loads configs, connects adapters, starts background
        tasks, and blocks until shutdown.
        """
        from ...config import get_settings

        self._db_factory = db_factory
        self._redis = redis
        self._arq_pool = arq_pool
        self._running = True
        settings = get_settings()

        logger.info("[GATEWAY] Starting shard %d", self.shard)

        # Initial adapter sync
        await self._sync_adapters()

        # Start background tasks
        self._background_tasks = {
            asyncio.create_task(self._heartbeat()),
            asyncio.create_task(self._reconnect_watcher()),
            asyncio.create_task(self._delivery_consumer()),
            asyncio.create_task(self._session_reaper()),
            asyncio.create_task(self._media_cache_cleaner()),
            asyncio.create_task(self._reload_listener()),
        }

        # Start cron scheduler
        from .scheduler import CronScheduler

        scheduler = CronScheduler(lock_dir=settings.gateway_lock_dir)
        self._background_tasks.add(
            asyncio.create_task(
                scheduler.run_loop(db_factory, arq_pool, interval=settings.gateway_tick_interval)
            )
        )

        # Publish status
        if self._redis:
            import json

            await self._redis.setex(
                "tesslate:gateway:status",
                120,
                json.dumps(
                    {
                        "shard": self.shard,
                        "adapters": len(self.adapters),
                        "started_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )

        logger.info(
            "[GATEWAY] Shard %d running with %d adapters, %d background tasks",
            self.shard,
            len(self.adapters),
            len(self._background_tasks),
        )

        # Block until shutdown
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("[GATEWAY] Shutting down shard %d", self.shard)
        self._running = False

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        for task in self._background_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Disconnect adapters
        for config_id, adapter in self.adapters.items():
            try:
                await adapter.disconnect()
            except Exception:
                logger.exception("[GATEWAY] Error disconnecting adapter %s", config_id)

        # Delete Redis active keys
        if self._redis:
            for config_id in self.adapters:
                await self._redis.delete(f"tesslate:gateway:active:{config_id}")
            await self._redis.delete("tesslate:gateway:status")

        self.adapters.clear()
        self._shutdown_event.set()
        logger.info("[GATEWAY] Shard %d stopped", self.shard)

    # ------------------------------------------------------------------
    # Adapter sync & hot-reload
    # ------------------------------------------------------------------

    async def _sync_adapters(self) -> None:
        """Load configs from DB, connect new adapters, disconnect removed ones.

        Diff-based: already-connected adapters are left alone. Only new configs
        get connected and removed/deactivated configs get disconnected.
        """
        from sqlalchemy import select

        from ...models import ChannelConfig
        from ..channels.base import GatewayAdapter
        from ..channels.registry import decrypt_credentials, get_channel

        async with self._db_factory() as db:
            result = await db.execute(
                select(ChannelConfig).where(
                    ChannelConfig.is_active.is_(True),
                    ChannelConfig.gateway_shard == self.shard,
                )
            )
            configs = result.scalars().all()
            db_configs = {str(c.id): c for c in configs}

        desired_ids = set(db_configs.keys())
        current_ids = set(self.adapters.keys())

        # Disconnect removed/deactivated configs
        to_remove = current_ids - desired_ids
        for config_id in to_remove:
            adapter = self.adapters.pop(config_id)
            try:
                await adapter.disconnect()
            except Exception:
                logger.exception("[GATEWAY] Error disconnecting adapter %s", config_id)
            if self._redis:
                await self._redis.delete(f"tesslate:gateway:active:{config_id}")
            self._failed_adapters.pop(config_id, None)
            self._failed_timestamps.pop(config_id, None)
            logger.info("[GATEWAY] Removed adapter %s", config_id)

        # Connect new configs
        to_add = desired_ids - current_ids
        for config_id in to_add:
            config = db_configs[config_id]
            try:
                credentials = decrypt_credentials(config.credentials)
                adapter = get_channel(config.channel_type, credentials)

                if not isinstance(adapter, GatewayAdapter):
                    continue
                adapter.config_id = config_id
                if not adapter.supports_gateway:
                    continue

                async def _tagged_handler(event, _cid=config_id):
                    event.config_id = _cid
                    await self._handle_message(event)

                adapter.set_message_handler(_tagged_handler)
                if await adapter.connect():
                    self.adapters[config_id] = adapter
                    if self._redis:
                        await self._redis.setex(f"tesslate:gateway:active:{config_id}", 60, "alive")
                    logger.info(
                        "[GATEWAY] Connected %s (config=%s)",
                        config.channel_type,
                        config_id,
                    )
                else:
                    self._failed_adapters[config_id] = 0
                    logger.warning(
                        "[GATEWAY] Failed to connect %s (config=%s)",
                        config.channel_type,
                        config_id,
                    )
            except Exception:
                logger.exception("[GATEWAY] Error connecting adapter %s", config_id)

        logger.info(
            "[GATEWAY] Sync complete: %d adapters (%d added, %d removed)",
            len(self.adapters),
            len(to_add),
            len(to_remove),
        )

    async def _reload_listener(self) -> None:
        """Subscribe to tesslate:gateway:reload and re-sync adapters on signal.

        Uses Redis pub/sub — same cross-pod pattern as tesslate:ws:* channels.
        Works identically in Docker (single Redis) and K8s (shared Redis/ElastiCache).
        """
        if not self._redis:
            logger.warning("[GATEWAY] No Redis — reload listener disabled")
            return

        pubsub = self._redis.pubsub()
        await pubsub.subscribe("tesslate:gateway:reload")
        logger.info("[GATEWAY] Reload listener subscribed")

        try:
            while self._running:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "message":
                    logger.info("[GATEWAY] Reload signal received, syncing adapters...")
                    try:
                        await self._sync_adapters()
                    except Exception:
                        logger.exception("[GATEWAY] Adapter sync failed after reload signal")
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe("tesslate:gateway:reload")
            await pubsub.aclose()

    # ------------------------------------------------------------------
    # Message handling with per-session ordering
    # ------------------------------------------------------------------

    async def _handle_message(self, event) -> None:
        """
        Per-session ordering via sentinel (synchronous placement, no race window).

        Different sessions process fully in parallel. Same-session messages are
        queued and processed sequentially.
        """
        key = event.source.session_key()

        # If a task is already running for this session, queue the message
        if key in self._active_sessions:
            self._pending_messages.setdefault(key, []).append(event)
            logger.debug("[GATEWAY] Queued message for busy session %s", key)
            return

        # Mark session as active (sync, before any await)
        self._active_sessions[key] = _PENDING_SENTINEL

        try:
            await self._process_message(event, key)
        except Exception:
            logger.exception("[GATEWAY] Error processing message for session %s", key)
            self._active_sessions.pop(key, None)
            self._pending_messages.pop(key, None)

    async def _process_message(self, event, session_key: str) -> None:
        """Resolve identity, find/create session, enqueue agent task."""
        from sqlalchemy import select

        from ...config import get_settings
        from ...models import ChannelConfig, ChannelMessage, Message, PlatformIdentity

        settings = get_settings()

        async with self._db_factory() as db:
            # 1. Find the ChannelConfig for this adapter
            config_id = self._find_config_id_for_event(event)
            if not config_id:
                logger.warning("[GATEWAY] No config found for event on %s", event.source.platform)
                self._active_sessions.pop(session_key, None)
                return

            config = await db.scalar(
                select(ChannelConfig).where(ChannelConfig.id == uuid.UUID(config_id))
            )
            if not config or not config.project_id:
                logger.warning("[GATEWAY] Config %s has no project", config_id)
                self._active_sessions.pop(session_key, None)
                return

            # 2. Resolve user — try linked identity first, fall back to config owner
            identity = await db.scalar(
                select(PlatformIdentity).where(
                    PlatformIdentity.platform == event.source.platform,
                    PlatformIdentity.platform_user_id == event.source.user_id,
                    PlatformIdentity.is_verified.is_(True),
                )
            )

            if identity:
                user_id = identity.user_id
            else:
                # No linked identity — use the config owner directly.
                # This is the common case: user set up their own bot.
                user_id = config.user_id
                logger.info(
                    "[GATEWAY] No linked identity for %s:%s, using config owner %s",
                    event.source.platform,
                    event.source.user_id,
                    user_id,
                )

            # 3. Find or create session
            chat = await self._find_or_create_session(db, event.source, user_id, config, settings)

            # 4. Transcribe voice if needed
            text = event.text
            if event.message_type.value == "voice" and event.media_urls:
                text = await self._transcribe_voice(event)

            if not text:
                self._active_sessions.pop(session_key, None)
                return

            # 5. Store inbound audit
            task_id = str(uuid.uuid4())
            channel_message = ChannelMessage(
                channel_config_id=config.id,
                direction="inbound",
                jid=f"{event.source.platform}:{event.source.chat_id}",
                sender_name=event.source.user_name,
                content=text,
                platform_message_id=event.message_id,
                task_id=task_id,
                status="delivered",
            )
            db.add(channel_message)

            # 6. Store user message
            user_message = Message(chat_id=chat.id, role="user", content=text)
            db.add(user_message)
            await db.commit()

            # 7. Build and enqueue agent task
            from ...models import Project
            from ..agent_task import AgentTaskPayload

            project = await db.scalar(select(Project).where(Project.id == config.project_id))

            payload = AgentTaskPayload(
                task_id=task_id,
                user_id=str(user_id),
                project_id=str(config.project_id),
                project_slug=project.slug if project else "",
                chat_id=str(chat.id),
                message=text,
                agent_id=str(config.default_agent_id) if config.default_agent_id else None,
                channel_config_id=str(config.id),
                channel_jid=f"{event.source.platform}:{event.source.chat_id}",
                channel_type=event.source.platform,
                gateway_deliver="origin",
                session_key=session_key,
            )

            from ..task_queue import get_task_queue

            await get_task_queue().enqueue("execute_agent_task", payload.to_dict())
            self._active_sessions[session_key] = task_id

            # Fire-and-forget stream watcher for real-time status
            task = asyncio.create_task(
                self._stream_watcher(task_id, config_id, event.source.chat_id, session_key)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            logger.info(
                "[GATEWAY] Enqueued task %s for session %s (user=%s)",
                task_id,
                session_key,
                user_id,
            )

    def _find_config_id_for_event(self, event) -> str | None:
        """Find the config_id of the adapter that produced this event."""
        config_id = getattr(event, "config_id", None)
        if config_id and config_id in self.adapters:
            return config_id
        for cid, adapter in self.adapters.items():
            if adapter.channel_type == event.source.platform:
                return cid
        return None

    # ------------------------------------------------------------------
    # Stream watcher — real-time tool status for messaging platforms
    # ------------------------------------------------------------------

    _TOOL_STATUS_MAP: dict[str, str] = {
        "read_file": "\U0001f4c4 Reading {arg}...",
        "write_file": "\u270f\ufe0f Writing {arg}...",
        "patch_file": "\u270f\ufe0f Editing {arg}...",
        "multi_edit": "\u270f\ufe0f Editing files...",
        "bash_exec": "\u26a1 Running command...",
        "shell_exec": "\u26a1 Running command...",
        "shell_open": "\u26a1 Opening shell...",
        "web_search": "\U0001f50d Searching the web...",
        "web_fetch": "\U0001f310 Fetching URL...",
        "get_project_info": "\U0001f4cb Checking project info...",
        "todo_read": "\U0001f4dd Reading tasks...",
        "todo_write": "\U0001f4dd Updating tasks...",
        "send_message": "\U0001f4ac Sending message...",
        "load_skill": "\U0001f9e9 Loading skill...",
    }

    async def _stream_watcher(
        self, task_id: str, config_id: str, chat_id: str, session_key: str
    ) -> None:
        """Watch agent Redis stream and send real-time status to messaging platform.

        Fire-and-forget task launched after ARQ enqueue. Subscribes to the
        per-task agent event stream and sends lightweight status updates
        (typing indicators + editable status messages) to the platform.

        Self-terminates on complete/done/error or after TIMEOUT seconds.
        Failure here must NOT prevent final delivery.
        """
        import time

        from ..pubsub import get_pubsub

        adapter = self.adapters.get(config_id)
        if not adapter:
            return

        status_message_id: str | None = None
        last_status_time = 0.0
        last_typing_time = 0.0
        _MIN_STATUS_INTERVAL = 3.0  # rate-limit platform API calls
        _TYPING_INTERVAL = 5.0
        _TIMEOUT = 600  # 10 min matches worker_job_timeout

        pubsub = get_pubsub()
        event_iter = pubsub.subscribe_agent_events(task_id).__aiter__()

        try:
            # Immediate typing indicator
            await adapter.set_typing(chat_id, on=True)
            last_typing_time = time.monotonic()

            start_time = time.monotonic()

            while time.monotonic() - start_time < _TIMEOUT:
                try:
                    event = await asyncio.wait_for(event_iter.__anext__(), timeout=3.0)
                except TimeoutError:
                    now = time.monotonic()
                    if now - last_typing_time >= _TYPING_INTERVAL:
                        await adapter.set_typing(chat_id, on=True)
                        last_typing_time = now
                    continue
                except StopAsyncIteration:
                    break

                event_type = event.get("type", "")

                # Terminal events — clean up and stop
                if event_type in ("complete", "done"):
                    if status_message_id:
                        with contextlib.suppress(Exception):
                            await adapter.delete_message(chat_id, status_message_id)
                    return

                if event_type == "error":
                    error_text = "\u274c Something went wrong"
                    with contextlib.suppress(Exception):
                        await adapter.send_status(chat_id, error_text, status_message_id)
                    return

                # Per-tool streaming — update status immediately
                if event_type == "tool_call":
                    tc_data = event.get("data", {})
                    now = time.monotonic()
                    if now - last_status_time >= _MIN_STATUS_INTERVAL:
                        tc_name = tc_data.get("name", "")
                        tc_params = tc_data.get("parameters", {})
                        status_text = self._build_status_text(
                            [{"name": tc_name, "parameters": tc_params}]
                        )
                        if status_text:
                            with contextlib.suppress(Exception):
                                new_id = await adapter.send_status(
                                    chat_id,
                                    status_text,
                                    status_message_id,
                                )
                                if new_id:
                                    status_message_id = new_id
                                last_status_time = now

                # Agent step summary — extract tool calls for status
                elif event_type == "agent_step":
                    step_data = event.get("data", {})
                    tool_calls = step_data.get("tool_calls", [])

                    if tool_calls:
                        now = time.monotonic()
                        if now - last_status_time >= _MIN_STATUS_INTERVAL:
                            status_text = self._build_status_text(tool_calls)
                            if status_text:
                                with contextlib.suppress(Exception):
                                    new_id = await adapter.send_status(
                                        chat_id,
                                        status_text,
                                        status_message_id,
                                    )
                                    if new_id:
                                        status_message_id = new_id
                                    last_status_time = now
                    else:
                        # Thinking — refresh typing
                        now = time.monotonic()
                        if now - last_typing_time >= _TYPING_INTERVAL:
                            await adapter.set_typing(chat_id, on=True)
                            last_typing_time = now

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug(
                "[GATEWAY] Stream watcher error for task %s",
                task_id,
                exc_info=True,
            )
        finally:
            with contextlib.suppress(Exception):
                await event_iter.aclose()  # type: ignore[attr-defined]
            if status_message_id:
                with contextlib.suppress(Exception):
                    await adapter.delete_message(chat_id, status_message_id)

    def _build_status_text(self, tool_calls: list[dict]) -> str:
        """Build human-readable status from agent tool calls."""
        parts: list[str] = []
        for tc in tool_calls:
            name = tc.get("name", "")
            params = tc.get("parameters", {})
            template = self._TOOL_STATUS_MAP.get(name)
            if template:
                arg = (
                    params.get("file_path")
                    or params.get("path")
                    or (params.get("command") or "")[:40]
                    or (params.get("query") or "")[:40]
                    or ""
                )
                if arg and len(arg) > 30:
                    arg = "..." + arg[-27:]
                if arg:
                    parts.append(template.format(arg=arg))
                else:
                    parts.append(template.format(arg="").rstrip(". ") + "...")
            else:
                parts.append(f"\u2699\ufe0f {name}...")
        return "\n".join(parts[:3])

    async def _find_or_create_session(self, db, source, user_id, config, settings):
        """Find existing active session or create new one."""
        from sqlalchemy import select

        from ...models import Chat

        key = source.session_key()
        now = datetime.now(UTC)

        chat = await db.scalar(
            select(Chat).where(
                Chat.session_key == key,
                Chat.status != "archived",
            )
        )

        # Check expiry
        if chat and chat.last_active_at:
            timeout = chat.idle_timeout_minutes or settings.gateway_session_idle_minutes
            if (now - chat.last_active_at).total_seconds() > timeout * 60:
                chat.status = "archived"
                await db.flush()
                chat = None

        if not chat:
            chat = Chat(
                user_id=user_id,
                project_id=config.project_id,
                origin="gateway",
                session_key=key,
                platform=source.platform,
                platform_chat_id=source.chat_id,
                platform_thread_id=source.thread_id or None,
                channel_config_id=config.id,
                last_active_at=now,
                title=f"[{source.platform}] {source.user_name or 'user'}",
            )
            db.add(chat)
            await db.flush()

        chat.last_active_at = now
        await db.flush()
        return chat

    async def _transcribe_voice(self, event) -> str:
        """Download and transcribe a voice message."""
        try:
            from ..channels.media import get_media_pipeline

            pipeline = get_media_pipeline()

            # Resolve platform-specific file URL
            adapter = None
            for a in self.adapters.values():
                if a.channel_type == event.source.platform:
                    adapter = a
                    break

            if not adapter:
                return "[Voice message — no adapter]"

            file_url = event.media_urls[0]

            # For Telegram, resolve file_id to URL
            if event.source.platform == "telegram" and hasattr(adapter, "get_file_url"):
                resolved = await adapter.get_file_url(file_url)
                if resolved:
                    file_url = resolved

            local_path = await pipeline.cache_media(file_url, event.source.platform, "audio")
            return await pipeline.transcribe_audio(local_path)

        except Exception as e:
            logger.error("[GATEWAY] Voice transcription failed: %s", e)
            return "[Voice message — transcription failed]"

    async def _send_pairing_prompt(self, event, db) -> None:
        """Send a pairing code to an unknown user."""
        import secrets
        import string

        from ...config import get_settings
        from ...models import PlatformIdentity

        settings = get_settings()

        # Check rate limit and max pending
        from sqlalchemy import func, select

        pending_count = await db.scalar(
            select(func.count())
            .select_from(PlatformIdentity)
            .where(
                PlatformIdentity.platform == event.source.platform,
                PlatformIdentity.platform_user_id == event.source.user_id,
                PlatformIdentity.is_verified.is_(False),
            )
        )

        if pending_count and pending_count >= settings.gateway_pairing_max_pending:
            return  # Too many pending, silently ignore

        # Generate 8-char code from unambiguous alphabet
        alphabet = string.ascii_uppercase.replace("O", "").replace("I", "")
        alphabet += string.digits.replace("0", "").replace("1", "")
        code = "".join(secrets.choice(alphabet) for _ in range(8))

        identity = PlatformIdentity(
            platform=event.source.platform,
            platform_user_id=event.source.user_id,
            platform_username=event.source.user_name,
            pairing_code=code,
            pairing_expires_at=datetime.now(UTC)
            + timedelta(seconds=settings.gateway_pairing_code_ttl),
        )
        db.add(identity)
        await db.commit()

        # Send pairing message via the adapter
        adapter = self.adapters.get(self._find_config_id_for_event(event) or "")
        if adapter:
            jid = f"{event.source.platform}:{event.source.chat_id}"
            await adapter.send_message(
                jid,
                f"Link your OpenSail account: go to Settings → Connections "
                f"and enter code **{code}**\n\nThis code expires in 1 hour.",
            )

    # ------------------------------------------------------------------
    # Delivery consumer — processes agent responses
    # ------------------------------------------------------------------

    async def _delivery_consumer(self) -> None:
        """XREADGROUP on tesslate:gateway:deliveries stream.

        Cross-pod delivery routing is Redis-only. On desktop (no redis_url) the
        worker also skips XADD delivery — disable this consumer entirely.
        """
        if not self._redis:
            logger.info("[GATEWAY] No Redis — delivery consumer disabled")
            return

        import redis.exceptions

        from ...config import get_settings

        settings = get_settings()
        stream = settings.gateway_delivery_stream
        group = f"gateway-shard-{self.shard}"
        consumer = f"consumer-{os.getpid()}"

        # Create consumer group if not exists
        with contextlib.suppress(redis.exceptions.ResponseError):
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)

        while self._running:
            try:
                entries = await self._redis.xreadgroup(
                    group,
                    consumer,
                    {stream: ">"},
                    count=10,
                    block=5000,
                )
                if not entries:
                    continue

                for _stream_name, messages in entries:
                    for msg_id, data in messages:
                        await self._process_delivery(data)
                        await self._redis.xack(stream, group, msg_id)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[GATEWAY] Delivery consumer error")
                await asyncio.sleep(2)

    async def _process_delivery(self, data: dict) -> None:
        """Process a single delivery from the stream.

        The envelope is parsed via :func:`envelope.parse_envelope` so we get a
        normalized dict with a real ``kind`` (defaulted to ``"message"`` for
        backward compatibility) and a decoded ``artifact_refs`` list. Phase 0
        only renders ``kind="message"``; ``"approval_card"`` (Phase 2) and
        ``"artifact"`` (Phase 4) are accepted but skipped (and acked by the
        caller) so unknown kinds never crash or loop.
        """
        from .envelope import (
            KIND_APPROVAL_CARD,
            KIND_ARTIFACT,
            KIND_MESSAGE,
            parse_envelope,
        )

        parsed = parse_envelope(data)
        kind = parsed["kind"]
        config_id = parsed["config_id"]
        session_key = parsed["session_key"]
        body = parsed["body"]
        artifact_refs = parsed["artifact_refs"]
        task_id = parsed["task_id"]

        # Phase 2 / Phase 4 envelope kinds — accept but no-op for now so the
        # producer can begin emitting them without a coordinated deploy.
        if kind in (KIND_APPROVAL_CARD, KIND_ARTIFACT):
            logger.info(
                "[GATEWAY] delivery kind=%s not yet implemented "
                "(lands in Phase 2/4); skipping session=%s task=%s",
                kind,
                session_key,
                task_id,
            )
            # Still release the session so the next pending message can flow.
            self._active_sessions.pop(session_key, None)
            pending = self._pending_messages.pop(session_key, [])
            if pending:
                next_event = pending[0]
                if len(pending) > 1:
                    self._pending_messages[session_key] = pending[1:]
                asyncio.create_task(self._handle_message(next_event))
            return

        if kind != KIND_MESSAGE:
            # Unknown kind from a future producer — log + skip rather than
            # crash. The XACK in the consumer loop ensures we don't replay it.
            logger.warning(
                "[GATEWAY] unknown delivery kind=%r — skipping session=%s",
                kind,
                session_key,
            )
            return

        if not body:
            return

        if artifact_refs:
            # Phase 4 will resolve and attach these. For now just log.
            logger.debug(
                "[GATEWAY] delivery has %d artifact_refs (ignored in Phase 0)",
                len(artifact_refs),
            )

        adapter = self.adapters.get(config_id)
        if not adapter:
            logger.warning("[GATEWAY] No adapter for delivery to config %s", config_id)
            return

        # Determine chat_id from the session_key
        # Format: platform:chat_type:chat_id[:thread_id]
        parts = session_key.split(":")
        chat_id = parts[2] if len(parts) >= 3 else session_key

        try:
            if hasattr(adapter, "send_gateway_response"):
                await adapter.send_gateway_response(chat_id, body)
            else:
                jid = f"{adapter.channel_type}:{chat_id}"
                await adapter.send_message(jid, body)

            logger.info("[GATEWAY] Delivered response to session %s", session_key)
        except Exception:
            logger.exception("[GATEWAY] Delivery failed for session %s", session_key)

        # Store outbound audit
        try:
            from ...models import ChannelMessage

            async with self._db_factory() as db:
                msg = ChannelMessage(
                    channel_config_id=uuid.UUID(config_id) if config_id else None,
                    direction="outbound",
                    jid=f"{adapter.channel_type}:{chat_id}",
                    content=body[:2000],
                    task_id=task_id,
                    status="delivered",
                )
                db.add(msg)
                await db.commit()
        except Exception:
            logger.warning("[GATEWAY] Failed to store outbound audit")

        # Release session and process pending
        self._active_sessions.pop(session_key, None)

        pending = self._pending_messages.pop(session_key, [])
        if pending:
            next_event = pending[0]
            if len(pending) > 1:
                self._pending_messages[session_key] = pending[1:]
            asyncio.create_task(self._handle_message(next_event))

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _heartbeat(self) -> None:
        """Refresh Redis active keys every 30s."""
        while self._running:
            try:
                if self._redis:
                    for config_id in self.adapters:
                        await self._redis.setex(f"tesslate:gateway:active:{config_id}", 60, "alive")
                    import json

                    await self._redis.setex(
                        "tesslate:gateway:status",
                        120,
                        json.dumps(
                            {
                                "shard": self.shard,
                                "adapters": len(self.adapters),
                                "active_sessions": len(self._active_sessions),
                                "heartbeat": datetime.now(UTC).isoformat(),
                            }
                        ),
                    )
            except Exception:
                logger.warning("[GATEWAY] Heartbeat error", exc_info=True)
            await asyncio.sleep(30)

    async def _reconnect_watcher(self) -> None:
        """Periodically try to reconnect failed adapters."""
        while self._running:
            await asyncio.sleep(10)

            for config_id, attempts in list(self._failed_adapters.items()):
                if attempts >= _RECONNECT_MAX_ATTEMPTS:
                    continue

                # Check backoff
                last_fail = self._failed_timestamps.get(config_id, 0)
                backoff = min(_RECONNECT_BACKOFF_BASE * (2**attempts), _RECONNECT_BACKOFF_CAP)
                import time

                if time.time() - last_fail < backoff:
                    continue

                adapter = self.adapters.get(config_id)
                if adapter and adapter.is_connected:
                    del self._failed_adapters[config_id]
                    continue

                # Try reconnect
                if adapter:
                    try:
                        if await adapter.connect():
                            del self._failed_adapters[config_id]
                            if self._redis:
                                await self._redis.setex(
                                    f"tesslate:gateway:active:{config_id}", 60, "alive"
                                )
                            logger.info("[GATEWAY] Reconnected adapter %s", config_id)
                        else:
                            self._failed_adapters[config_id] = attempts + 1
                            self._failed_timestamps[config_id] = time.time()
                    except Exception:
                        self._failed_adapters[config_id] = attempts + 1
                        self._failed_timestamps[config_id] = time.time()
                        logger.warning(
                            "[GATEWAY] Reconnect attempt %d failed for %s",
                            attempts + 1,
                            config_id,
                        )

    async def _session_reaper(self) -> None:
        """Archive sessions that have been idle past their timeout."""
        while self._running:
            await asyncio.sleep(60)

            try:
                from sqlalchemy import select

                from ...config import get_settings
                from ...models import Chat

                settings = get_settings()
                now = datetime.now(UTC)

                async with self._db_factory() as db:
                    result = await db.execute(
                        select(Chat).where(
                            Chat.session_key.isnot(None),
                            Chat.status == "active",
                            Chat.last_active_at
                            < now - timedelta(minutes=settings.gateway_session_idle_minutes),
                        )
                    )
                    stale = result.scalars().all()
                    for chat in stale:
                        chat.status = "archived"
                    if stale:
                        await db.commit()
                        logger.info("[GATEWAY] Archived %d idle sessions", len(stale))
            except Exception:
                logger.warning("[GATEWAY] Session reaper error", exc_info=True)

    async def _media_cache_cleaner(self) -> None:
        """Clean up old media cache files hourly."""
        while self._running:
            await asyncio.sleep(3600)

            try:
                from ...config import get_settings
                from ..channels.media import get_media_pipeline

                settings = get_settings()
                pipeline = get_media_pipeline()
                await pipeline.cleanup_cache(
                    max_age_hours=settings.gateway_media_cache_max_age_hours
                )
            except Exception:
                logger.warning("[GATEWAY] Media cache cleanup error", exc_info=True)
