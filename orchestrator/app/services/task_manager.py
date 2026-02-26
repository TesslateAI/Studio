"""
Background Task Manager
Tracks status of long-running operations to prevent blocking the event loop.

Supports Redis-backed state for cross-pod visibility when horizontally scaled.
Falls back to in-memory only when Redis is unavailable.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

TASK_KEY_PREFIX = "tesslate:task:"
USER_TASKS_KEY_PREFIX = "tesslate:user_tasks:"
TASK_UPDATE_CHANNEL = "tesslate:task_updates"
TASK_TTL = 86400  # 24 hours


class TaskStatus(StrEnum):
    """Task execution statuses"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    """Represents progress of a task"""

    current: int = 0
    total: int = 100
    message: str = ""

    @property
    def percentage(self) -> int:
        if self.total == 0:
            return 0
        return int((self.current / self.total) * 100)


@dataclass
class Task:
    """Represents a background task"""

    id: str
    user_id: UUID  # Changed from int to UUID to match User model
    type: str  # e.g., "project_creation", "project_deletion", "container_startup"
    status: TaskStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: TaskProgress = field(default_factory=TaskProgress)
    result: Any | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_log(self, message: str):
        """Add a log message with timestamp"""
        timestamp = datetime.utcnow().isoformat()
        self.logs.append(f"[{timestamp}] {message}")

    def update_progress(self, current: int, total: int, message: str = ""):
        """Update task progress"""
        self.progress.current = current
        self.progress.total = total
        if message:
            self.progress.message = message
            self.add_log(message)

    def to_dict(self) -> dict:
        """Convert task to dictionary for API responses"""
        return {
            "id": self.id,
            "user_id": str(self.user_id),  # Convert UUID to string for JSON serialization
            "type": self.type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": {
                "current": self.progress.current,
                "total": self.progress.total,
                "percentage": self.progress.percentage,
                "message": self.progress.message,
            },
            "result": self.result,
            "error": self.error,
            "logs": self.logs[-50:],  # Return last 50 log entries
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Reconstruct a Task from a dict (e.g., loaded from Redis)."""
        progress_data = data.get("progress", {})
        return cls(
            id=data["id"],
            user_id=UUID(data["user_id"]),
            type=data["type"],
            status=TaskStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=(
                datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            progress=TaskProgress(
                current=progress_data.get("current", 0),
                total=progress_data.get("total", 100),
                message=progress_data.get("message", ""),
            ),
            result=data.get("result"),
            error=data.get("error"),
            logs=data.get("logs", []),
            metadata=data.get("metadata", {}),
        )


class TaskManager:
    """Manages background tasks with status tracking.

    Stores task state both locally (in-memory) and in Redis (when available)
    for cross-pod visibility in horizontally scaled deployments.
    """

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._user_tasks: dict[UUID, list[str]] = defaultdict(list)  # Changed from int to UUID
        self._background_tasks: dict[str, asyncio.Task] = {}
        self._callbacks: dict[str, list[Callable]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def _store_task_redis(self, task: Task):
        """Store task state in Redis for cross-pod visibility."""
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        try:
            task_key = f"{TASK_KEY_PREFIX}{task.id}"
            user_key = f"{USER_TASKS_KEY_PREFIX}{task.user_id}"

            # Store task data as JSON
            await redis.setex(task_key, TASK_TTL, json.dumps(task.to_dict()))

            # Add task ID to user's task set
            await redis.sadd(user_key, task.id)
            await redis.expire(user_key, TASK_TTL)
        except Exception as e:
            logger.debug(f"Failed to store task in Redis (non-blocking): {e}")

    async def _publish_task_update(self, task: Task):
        """Publish task update via Redis Pub/Sub for cross-pod WebSocket delivery."""
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        try:
            await redis.publish(
                TASK_UPDATE_CHANNEL,
                json.dumps({"type": "task_update", "task": task.to_dict()}),
            )
        except Exception as e:
            logger.debug(f"Failed to publish task update (non-blocking): {e}")

    async def _load_task_redis(self, task_id: str) -> Task | None:
        """Load task state from Redis (for cross-pod queries)."""
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return None

        try:
            task_key = f"{TASK_KEY_PREFIX}{task_id}"
            data = await redis.get(task_key)
            if data:
                return Task.from_dict(json.loads(data))
        except Exception as e:
            logger.debug(f"Failed to load task from Redis: {e}")

        return None

    def create_task(
        self,
        user_id: UUID,
        task_type: str,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> Task:
        """Create a new task and return it.

        Args:
            task_id: Optional pre-generated ID. When provided the task is stored
                     under this key so that later ``update_task_status(task_id)``
                     can locate it without a dict-key mismatch.
        """
        task_id = task_id or str(uuid.uuid4())
        task = Task(
            id=task_id,
            user_id=user_id,
            type=task_type,
            status=TaskStatus.QUEUED,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )

        self._tasks[task_id] = task
        self._user_tasks[user_id].append(task_id)

        # Non-blocking Redis store
        asyncio.create_task(self._store_task_redis(task))

        return task

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID (local first, then Redis)"""
        task = self._tasks.get(task_id)
        if task:
            return task

        # Don't do async Redis lookup from sync method
        # Redis lookup happens in get_task_async
        return None

    async def get_task_async(self, task_id: str) -> Task | None:
        """Get a task by ID with Redis fallback for cross-pod visibility."""
        # Check local first
        task = self._tasks.get(task_id)
        if task:
            return task

        # Try Redis (task may be on another pod)
        task = await self._load_task_redis(task_id)
        if task:
            # Cache locally for future lookups
            self._tasks[task_id] = task
        return task

    def get_user_tasks(self, user_id: UUID, active_only: bool = False) -> list[Task]:
        """Get all tasks for a user (local only)"""
        task_ids = self._user_tasks.get(user_id, [])
        tasks = [self._tasks[tid] for tid in task_ids if tid in self._tasks]

        if active_only:
            tasks = [t for t in tasks if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)]

        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    async def get_user_tasks_async(self, user_id: UUID, active_only: bool = False) -> list[Task]:
        """Get all tasks for a user with Redis fallback for cross-pod visibility.

        When ``active_only`` is True, uses a Redis pipeline to batch-load task
        data and prunes completed/failed entries from the user set so it stays
        small over time.
        """
        from .cache_service import get_redis_client

        # Start with local tasks
        local_task_ids = set(self._user_tasks.get(user_id, []))

        # Try to get task IDs from Redis (includes tasks from other pods)
        redis = await get_redis_client()
        if redis:
            try:
                user_key = f"{USER_TASKS_KEY_PREFIX}{user_id}"
                redis_task_ids = await redis.smembers(user_key)
                if redis_task_ids:
                    for tid in redis_task_ids:
                        tid_str = tid if isinstance(tid, str) else tid.decode()
                        local_task_ids.add(tid_str)
            except Exception as e:
                logger.debug(f"Failed to load user tasks from Redis: {e}")

        if not local_task_ids:
            return []

        # Batch-load task data via Redis pipeline (avoids N+1 round-trips)
        all_task_ids = list(local_task_ids)
        tasks: list[Task] = []
        ids_to_prune: list[str] = []

        if redis:
            try:
                pipe = redis.pipeline(transaction=False)
                for tid in all_task_ids:
                    pipe.get(f"{TASK_KEY_PREFIX}{tid}")
                results = await pipe.execute()

                for tid, raw in zip(all_task_ids, results, strict=False):
                    if not raw:
                        ids_to_prune.append(tid)
                        continue
                    task = Task.from_dict(json.loads(raw))
                    self._tasks[tid] = task  # cache locally
                    if active_only and task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                        ids_to_prune.append(tid)
                        continue
                    tasks.append(task)
            except Exception as e:
                logger.debug(f"Pipeline load failed, falling back to sequential: {e}")
                # Fallback to sequential loading
                for tid in all_task_ids:
                    task = await self.get_task_async(tid)
                    if task:
                        if active_only and task.status not in (
                            TaskStatus.QUEUED,
                            TaskStatus.RUNNING,
                        ):
                            ids_to_prune.append(tid)
                            continue
                        tasks.append(task)
        else:
            # No Redis — local only
            for tid in all_task_ids:
                task = self._tasks.get(tid)
                if task:
                    if active_only and task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                        continue
                    tasks.append(task)

        # Prune completed/expired task IDs from the user set to keep it small
        if ids_to_prune and redis:
            try:
                user_key = f"{USER_TASKS_KEY_PREFIX}{user_id}"
                await redis.srem(user_key, *ids_to_prune)
                logger.debug(
                    f"Pruned {len(ids_to_prune)} inactive task IDs from user set {user_id}"
                )
            except Exception:
                pass  # non-blocking

        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    async def update_task_status(
        self, task_id: str, status: TaskStatus, error: str | None = None, result: Any | None = None
    ):
        """Update task status (local first, Redis fallback for cross-pod)."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                # Task may have been created on another pod — try Redis
                task = await self._load_task_redis(task_id)
                if not task:
                    return
                # Cache locally for future lookups
                self._tasks[task_id] = task

            task.status = status

            if status == TaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.utcnow()

            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = datetime.utcnow()
                if error:
                    task.error = error
                if result is not None:
                    task.result = result

            # Sync to Redis
            await self._store_task_redis(task)

            # Publish update to all pods via Pub/Sub
            await self._publish_task_update(task)

            # Notify local callbacks
            await self._notify_callbacks(task_id, task)

    async def run_task(self, task_id: str, coro: Callable, *args, **kwargs):
        """Run a coroutine as a background task with status tracking"""
        task = await self.get_task_async(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        try:
            await self.update_task_status(task_id, TaskStatus.RUNNING)
            task.add_log(f"Starting {task.type}")

            # Execute the coroutine
            result = await coro(*args, task=task, **kwargs)

            await self.update_task_status(task_id, TaskStatus.COMPLETED, result=result)
            task.add_log(f"Completed {task.type}")

            return result

        except Exception as e:
            error_msg = str(e)
            await self.update_task_status(task_id, TaskStatus.FAILED, error=error_msg)
            task.add_log(f"Failed: {error_msg}")
            raise

    def start_background_task(self, task_id: str, coro: Callable, *args, **kwargs) -> asyncio.Task:
        """Start a task in the background and return immediately"""
        logger.info(
            f"[TASK-MANAGER] Creating background task {task_id} for coroutine {coro.__name__}"
        )
        logger.info(
            f"[TASK-MANAGER] Args: {args[:3] if len(args) > 3 else args}"
        )  # First 3 args only

        async_task = asyncio.create_task(self.run_task(task_id, coro, *args, **kwargs))
        self._background_tasks[task_id] = async_task

        logger.info(f"[TASK-MANAGER] Background task {task_id} created and stored")
        return async_task

    def subscribe(self, task_id: str, callback: Callable):
        """Subscribe to task updates"""
        self._callbacks[task_id].append(callback)

    async def _notify_callbacks(self, task_id: str, task: Task):
        """Notify all subscribers of task updates"""
        callbacks = self._callbacks.get(task_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task)
                else:
                    callback(task)
            except Exception as e:
                logger.warning(f"Error in task callback: {e}")

    async def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Clean up old completed tasks"""
        async with self._lock:
            cutoff_time = datetime.utcnow()
            from datetime import timedelta

            cutoff_time = cutoff_time - timedelta(hours=max_age_hours)

            tasks_to_remove = []
            for task_id, task in self._tasks.items():
                if (
                    task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                    and task.completed_at
                    and task.completed_at < cutoff_time
                ):
                    tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                task = self._tasks.pop(task_id)
                if task.user_id in self._user_tasks:
                    with contextlib.suppress(ValueError):
                        self._user_tasks[task.user_id].remove(task_id)
                if task_id in self._background_tasks:
                    del self._background_tasks[task_id]
                if task_id in self._callbacks:
                    del self._callbacks[task_id]


# Global task manager instance
_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """Get the global task manager instance"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
