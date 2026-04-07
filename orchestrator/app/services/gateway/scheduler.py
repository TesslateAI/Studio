"""
Cron Scheduler — tick-based scheduler that lives inside the gateway process.

Checks the ``agent_schedules`` table every tick (default 60s) for due tasks,
advances ``next_run_at`` **before** execution (crash safety — no double-fire),
and enqueues agent tasks to ARQ.
"""

import asyncio
import fcntl
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from croniter import croniter

logger = logging.getLogger(__name__)


class CronScheduler:
    """File-lock-protected cron scheduler for agent schedules."""

    def __init__(self, lock_dir: str = "/var/run/tesslate"):
        self._running = False
        self._lock_dir = lock_dir
        self._lock_fd = None

    async def tick(self, db_factory, arq_pool) -> int:
        """
        Execute one scheduler tick.

        File-lock protected (non-blocking, skip if held).
        Returns the number of schedules fired.
        """
        lock_path = os.path.join(self._lock_dir, "cron-tick.lock")
        Path(self._lock_dir).mkdir(parents=True, exist_ok=True)

        fd = None
        try:
            fd = open(lock_path, "w")  # noqa: SIM115 — must stay open for lock duration
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if fd:
                fd.close()
            return 0  # Another tick is running

        try:
            return await self._execute_tick(db_factory, arq_pool)
        except Exception:
            logger.exception("[CRON] Tick error")
            return 0
        finally:
            if fd:
                fcntl.flock(fd, fcntl.LOCK_UN)
                fd.close()

    async def _execute_tick(self, db_factory, arq_pool) -> int:
        """Core tick logic — query due schedules and enqueue."""
        from sqlalchemy import select

        from ...models import AgentSchedule, Project
        from ..agent_task import AgentTaskPayload

        now = datetime.now(UTC)
        fired = 0

        async with db_factory() as db:
            result = await db.execute(
                select(AgentSchedule)
                .where(
                    AgentSchedule.is_active.is_(True),
                    AgentSchedule.next_run_at <= now,
                )
                .order_by(AgentSchedule.next_run_at.asc())
                .limit(50)
            )
            schedules = result.scalars().all()

            if not schedules:
                return 0

            for schedule in schedules:
                try:
                    # Advance next_run_at BEFORE execution (crash safety)
                    cron = croniter(schedule.normalized_cron, now)
                    schedule.next_run_at = cron.get_next(datetime)

                    # Render prompt template
                    prompt = _render_template(schedule.prompt_template, schedule, now)

                    # Load project for context
                    proj_result = await db.execute(
                        select(Project).where(Project.id == schedule.project_id)
                    )
                    project = proj_result.scalar_one_or_none()
                    if not project:
                        logger.warning(
                            "[CRON] Schedule %s references missing project %s",
                            schedule.id,
                            schedule.project_id,
                        )
                        schedule.last_status = "failed"
                        schedule.last_error = "Project not found"
                        continue

                    # Build and enqueue task
                    import uuid

                    task_id = str(uuid.uuid4())

                    # Create a chat session for this scheduled run
                    from ...models import Chat

                    chat = Chat(
                        user_id=schedule.user_id,
                        project_id=schedule.project_id,
                        origin="gateway",
                        title=f"[scheduled] {schedule.name}",
                    )
                    db.add(chat)
                    await db.flush()

                    from ...models import Message

                    user_message = Message(chat_id=chat.id, role="user", content=prompt)
                    db.add(user_message)

                    payload = AgentTaskPayload(
                        task_id=task_id,
                        user_id=str(schedule.user_id),
                        project_id=str(schedule.project_id),
                        project_slug=project.slug,
                        chat_id=str(chat.id),
                        message=prompt,
                        agent_id=str(schedule.agent_id) if schedule.agent_id else None,
                        gateway_deliver=schedule.deliver,
                        session_key=None,
                        schedule_id=str(schedule.id),
                        channel_config_id=(
                            str(schedule.origin_config_id) if schedule.origin_config_id else None
                        ),
                        channel_type=schedule.origin_platform,
                    )

                    await arq_pool.enqueue_job("execute_agent_task", payload.to_dict())

                    # Update schedule state
                    schedule.last_run_at = now
                    schedule.last_task_id = task_id
                    schedule.runs_completed = (schedule.runs_completed or 0) + 1
                    schedule.last_status = "enqueued"
                    schedule.last_error = None

                    # Check repeat limit
                    if schedule.repeat is not None and schedule.runs_completed >= schedule.repeat:
                        schedule.is_active = False
                        logger.info(
                            "[CRON] Schedule %s reached repeat limit (%d), deactivated",
                            schedule.id,
                            schedule.repeat,
                        )

                    fired += 1
                    logger.info(
                        "[CRON] Fired schedule '%s' (id=%s, task=%s)",
                        schedule.name,
                        schedule.id,
                        task_id,
                    )

                except Exception:
                    logger.exception("[CRON] Failed to fire schedule %s", schedule.id)
                    schedule.last_status = "failed"
                    schedule.last_error = "Tick execution error"

            await db.commit()

        return fired

    async def run_loop(self, db_factory, arq_pool, interval: int = 60) -> None:
        """Run the tick loop until stopped."""
        self._running = True
        logger.info("[CRON] Scheduler started (interval=%ds)", interval)

        while self._running:
            try:
                count = await self.tick(db_factory, arq_pool)
                if count:
                    logger.info("[CRON] Tick fired %d schedule(s)", count)
            except Exception:
                logger.exception("[CRON] Tick loop error")
            await asyncio.sleep(interval)

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False


def compute_next_run(normalized_cron: str, after: datetime | None = None) -> datetime:
    """Compute the next run time from a normalized cron expression."""
    base = after or datetime.now(UTC)
    cron = croniter(normalized_cron, base)
    return cron.get_next(datetime)


def _render_template(template: str, schedule, now: datetime) -> str:
    """Render prompt template variables."""
    weekdays = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    return (
        template.replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H:%M"))
        .replace("{weekday}", weekdays[now.weekday()])
        .replace("{schedule_name}", schedule.name)
    )
