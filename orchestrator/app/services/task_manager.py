"""
Background Task Manager
Tracks status of long-running operations to prevent blocking the event loop.
"""
import asyncio
import uuid
from uuid import UUID
from datetime import datetime
from typing import Dict, Optional, List, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict


class TaskStatus(str, Enum):
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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: TaskProgress = field(default_factory=TaskProgress)
    result: Optional[Any] = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

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

    def to_dict(self) -> Dict:
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
                "message": self.progress.message
            },
            "result": self.result,
            "error": self.error,
            "logs": self.logs[-50:],  # Return last 50 log entries
            "metadata": self.metadata
        }


class TaskManager:
    """Manages background tasks with status tracking"""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._user_tasks: Dict[UUID, List[str]] = defaultdict(list)  # Changed from int to UUID
        self._background_tasks: Dict[str, asyncio.Task] = {}
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def create_task(
        self,
        user_id: UUID,
        task_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Task:
        """Create a new task and return it"""
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            user_id=user_id,
            type=task_type,
            status=TaskStatus.QUEUED,
            created_at=datetime.utcnow(),
            metadata=metadata or {}
        )

        self._tasks[task_id] = task
        self._user_tasks[user_id].append(task_id)

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        return self._tasks.get(task_id)

    def get_user_tasks(self, user_id: UUID, active_only: bool = False) -> List[Task]:
        """Get all tasks for a user"""
        task_ids = self._user_tasks.get(user_id, [])
        tasks = [self._tasks[tid] for tid in task_ids if tid in self._tasks]

        if active_only:
            tasks = [
                t for t in tasks
                if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)
            ]

        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: Optional[str] = None,
        result: Optional[Any] = None
    ):
        """Update task status"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return

            task.status = status

            if status == TaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.utcnow()

            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = datetime.utcnow()
                if error:
                    task.error = error
                if result is not None:
                    task.result = result

            # Notify callbacks
            await self._notify_callbacks(task_id, task)

    async def run_task(
        self,
        task_id: str,
        coro: Callable,
        *args,
        **kwargs
    ):
        """Run a coroutine as a background task with status tracking"""
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        try:
            await self.update_task_status(task_id, TaskStatus.RUNNING)
            task.add_log(f"Starting {task.type}")

            # Execute the coroutine
            result = await coro(*args, task=task, **kwargs)

            await self.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result=result
            )
            task.add_log(f"Completed {task.type}")

            return result

        except Exception as e:
            error_msg = str(e)
            await self.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=error_msg
            )
            task.add_log(f"Failed: {error_msg}")
            raise

    def start_background_task(
        self,
        task_id: str,
        coro: Callable,
        *args,
        **kwargs
    ) -> asyncio.Task:
        """Start a task in the background and return immediately"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[TASK-MANAGER] Creating background task {task_id} for coroutine {coro.__name__}")
        logger.info(f"[TASK-MANAGER] Args: {args[:3] if len(args) > 3 else args}")  # First 3 args only

        async_task = asyncio.create_task(
            self.run_task(task_id, coro, *args, **kwargs)
        )
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
                print(f"Error in task callback: {e}")

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
                self._user_tasks[task.user_id].remove(task_id)
                if task_id in self._background_tasks:
                    del self._background_tasks[task_id]
                if task_id in self._callbacks:
                    del self._callbacks[task_id]


# Global task manager instance
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get the global task manager instance"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
