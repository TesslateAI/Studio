from uuid import UUID
"""
Shell Session Manager

Manages shell sessions with security policies, resource limits, and audit logging.
Designed for AI agent programmatic access.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import ShellSession, User, Project
from ..services.pty_broker import get_pty_broker, PTYSession
from ..config import get_settings
from ..utils.resource_naming import get_container_name

logger = logging.getLogger(__name__)
settings = get_settings()


class ShellSessionManager:
    """Manages shell sessions with security and resource controls."""

    # Configuration
    MAX_SESSIONS_PER_USER = 5  # Max concurrent shells per user (agents may need more)
    MAX_SESSIONS_PER_PROJECT = 3  # Max concurrent shells per project
    IDLE_TIMEOUT_MINUTES = 30  # Auto-close idle shells after 30 minutes
    MAX_SESSION_DURATION_HOURS = 8  # Force close after 8 hours
    MAX_OUTPUT_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB max buffer per session

    def __init__(self):
        self.pty_broker = get_pty_broker()
        self.active_sessions: Dict[str, PTYSession] = {}

    async def create_session(
        self,
        user_id: UUID,
        project_id: str,
        db: AsyncSession,
        command: str = "/bin/sh",
    ) -> Dict[str, Any]:
        """
        Create a new shell session with validation and resource limits.

        Returns session metadata including session_id.
        Raises HTTPException on validation failures.
        """
        from fastapi import HTTPException, status

        # 1. Validate user owns project
        result = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.owner_id == user_id
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project not found or access denied"
            )

        # 2. Check user session limits
        user_sessions = await self._get_user_active_sessions(user_id, db)
        if len(user_sessions) >= self.MAX_SESSIONS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Maximum {self.MAX_SESSIONS_PER_USER} concurrent sessions per user"
            )

        # 3. Check project session limits
        project_sessions = await self._get_project_active_sessions(project_id, db)
        if len(project_sessions) >= self.MAX_SESSIONS_PER_PROJECT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Maximum {self.MAX_SESSIONS_PER_PROJECT} concurrent sessions per project"
            )

        # 4. Get container/pod name based on deployment mode
        container_name = self._get_container_name(user_id, project_id)

        # 5. Verify container is running
        is_running = await self._is_container_running(user_id, project_id)
        if not is_running:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Development environment is not running"
            )

        # 6. Create PTY session
        try:
            pty_session = await self.pty_broker.create_session(
                user_id=user_id,
                project_id=project_id,
                container_name=container_name,
                command=command,
            )
        except Exception as e:
            logger.error(f"Failed to create PTY session: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create shell session: {str(e)}"
            )

        # 7. Save to database
        db_session = ShellSession(
            session_id=pty_session.session_id,
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=command,
            working_dir=pty_session.cwd,  # Get from PTYSession (already configured for deployment mode)
            status="active",
        )
        db.add(db_session)
        await db.commit()
        await db.refresh(db_session)

        # 8. Track in memory
        self.active_sessions[pty_session.session_id] = pty_session

        logger.info(
            f"Created shell session {pty_session.session_id} for user {user_id}, "
            f"project {project_id}, container {container_name}"
        )

        return {
            "session_id": pty_session.session_id,
            "status": "active",
            "created_at": pty_session.created_at.isoformat(),
        }

    async def write_to_session(
        self,
        session_id: str,
        data: bytes,
        db: AsyncSession,
    ) -> None:
        """Write data to PTY stdin."""

        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        await self.pty_broker.write_to_pty(session_id, data)

        # Update database stats
        await self._update_session_stats(session_id, db)

    async def read_output(
        self,
        session_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Read new output from session since last read.

        Returns:
            {
                "output": str (base64 encoded for binary safety),
                "bytes": int,
                "is_eof": bool
            }
        """
        import base64

        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Get new output
        new_data, is_eof = await session.read_new_output()

        # Update database stats
        await self._update_session_stats(session_id, db, read_count=1)

        return {
            "output": base64.b64encode(new_data).decode('utf-8'),
            "bytes": len(new_data),
            "is_eof": is_eof,
        }

    async def close_session(
        self,
        session_id: str,
        db: AsyncSession,
    ) -> None:
        """Close a shell session."""

        await self.pty_broker.close_session(session_id)

        # Update database
        result = await db.execute(
            select(ShellSession).where(ShellSession.session_id == session_id)
        )
        db_session = result.scalar_one_or_none()
        if db_session:
            db_session.status = "closed"
            db_session.closed_at = datetime.utcnow()
            await db.commit()

        # Remove from active sessions
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

        logger.info(f"Closed shell session {session_id}")

    async def list_sessions(
        self,
        user_id: UUID,
        project_id: Optional[UUID],
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """List all active sessions for a user/project."""

        query = select(ShellSession).where(
            ShellSession.user_id == user_id,
            ShellSession.status == "active"
        )

        if project_id:
            query = query.where(ShellSession.project_id == project_id)

        result = await db.execute(query)
        sessions = result.scalars().all()

        return [
            {
                "session_id": s.session_id,
                "project_id": s.project_id,
                "command": s.command,
                "working_dir": s.working_dir,
                "created_at": s.created_at.isoformat(),
                "last_activity_at": s.last_activity_at.isoformat(),
                "bytes_read": s.bytes_read,
                "bytes_written": s.bytes_written,
                "total_reads": s.total_reads,
            }
            for s in sessions
        ]

    async def cleanup_idle_sessions(self, db: AsyncSession) -> int:
        """
        Clean up idle sessions (background task).
        Returns number of sessions closed.
        """

        cutoff_time = datetime.utcnow() - timedelta(minutes=self.IDLE_TIMEOUT_MINUTES)

        result = await db.execute(
            select(ShellSession).where(
                ShellSession.status == "active",
                ShellSession.last_activity_at < cutoff_time
            )
        )
        idle_sessions = result.scalars().all()

        closed_count = 0
        for session in idle_sessions:
            try:
                await self.close_session(session.session_id, db)
                closed_count += 1
                logger.info(f"Auto-closed idle session {session.session_id}")
            except Exception as e:
                logger.error(f"Failed to close idle session {session.session_id}: {e}")

        return closed_count

    # Helper methods

    def _get_container_name(self, user_id: UUID, project_id: str) -> str:
        """Get container/pod name based on deployment mode."""
        if settings.deployment_mode == "kubernetes":
            # K8s pod name format
            return get_container_name(user_id, project_id, mode="kubernetes")
        else:
            # Docker container name format - use slug from container manager
            from ..dev_server_manager import get_container_manager
            manager = get_container_manager()
            project_key = f"user-{user_id}-project-{project_id}"
            container_info = manager.containers.get(project_key)

            if container_info:
                return container_info["container_name"]
            else:
                # Fallback: try to find container by labels
                import subprocess
                result = subprocess.run(
                    ["docker", "ps", "--filter", f"label=com.tesslate.devserver.project_id={project_id}",
                     "--filter", f"label=com.tesslate.devserver.user_id={user_id}", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip().split('\n')[0]
                else:
                    # Last resort fallback (should not happen in production)
                    return get_container_name(user_id, project_id, mode="docker")

    async def _is_container_running(self, user_id: UUID, project_id: str) -> bool:
        """Check if container/pod is running."""
        from ..dev_server_manager import get_container_manager

        manager = get_container_manager()
        status = await manager.get_container_status(str(project_id), user_id)
        return status.get("running", False)

    async def _get_user_active_sessions(
        self,
        user_id: UUID,
        db: AsyncSession
    ) -> List[ShellSession]:
        """Get all active sessions for a user."""
        result = await db.execute(
            select(ShellSession).where(
                ShellSession.user_id == user_id,
                ShellSession.status == "active"
            )
        )
        return list(result.scalars().all())

    async def _get_project_active_sessions(
        self,
        project_id: str,
        db: AsyncSession
    ) -> List[ShellSession]:
        """Get all active sessions for a project."""
        result = await db.execute(
            select(ShellSession).where(
                ShellSession.project_id == project_id,
                ShellSession.status == "active"
            )
        )
        return list(result.scalars().all())

    async def _update_session_stats(
        self,
        session_id: str,
        db: AsyncSession,
        read_count: int = 0
    ) -> None:
        """Update session statistics in database."""
        session = self.active_sessions.get(session_id)
        if not session:
            return

        result = await db.execute(
            select(ShellSession).where(ShellSession.session_id == session_id)
        )
        db_session = result.scalar_one_or_none()
        if db_session:
            db_session.bytes_read = session.bytes_read
            db_session.bytes_written = session.bytes_written
            db_session.last_activity_at = datetime.utcnow()
            if read_count > 0:
                db_session.total_reads += read_count
            await db.commit()


# Singleton instance
_shell_session_manager = None

def get_shell_session_manager() -> ShellSessionManager:
    """Get singleton shell session manager."""
    global _shell_session_manager
    if _shell_session_manager is None:
        _shell_session_manager = ShellSessionManager()
    return _shell_session_manager
