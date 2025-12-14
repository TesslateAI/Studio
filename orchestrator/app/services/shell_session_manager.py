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
    MAX_SESSIONS_PER_USER = 100  # Max concurrent shells per user
    MAX_SESSIONS_PER_PROJECT = 100  # Max concurrent shells per project
    IDLE_TIMEOUT_MINUTES = 30  # Auto-close idle shells after 30 minutes
    MAX_SESSION_DURATION_HOURS = 8  # Force close after 8 hours
    MAX_OUTPUT_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB max buffer per session

    def __init__(self):
        self.pty_broker = get_pty_broker()
        self.active_sessions: Dict[str, PTYSession] = {}
        # Track sessions that need stats updates (non-blocking batching)
        self.pending_stats_updates: set = set()
        self._stats_update_task = None

    async def create_session(
        self,
        user_id: UUID,
        project_id: str,
        db: AsyncSession,
        command: str = "/bin/sh",
        container_name: Optional[str] = None,  # For multi-container Docker: which container to connect to
    ) -> Dict[str, Any]:
        """
        Create a new shell session with validation and resource limits.

        Args:
            user_id: User UUID
            project_id: Project ID
            db: Database session
            command: Shell command to run (default: /bin/sh)
            container_name_hint: Optional container name for multi-container projects

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
        resolved_container_name = await self._get_container_name(
            user_id, project_id, project.slug, container_name
        )

        # 5. Verify container is running
        # IMPORTANT: Pass original container_name (not resolved) for K8s mode
        # because is_container_ready generates resource names from it internally
        is_running = await self._is_container_running(
            user_id, project_id, project.slug, container_name
        )
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
                container_name=resolved_container_name,
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
            container_name=resolved_container_name,
            command=command,
            working_dir=pty_session.cwd,  # Get from PTYSession (already configured for deployment mode)
            status="active",
        )
        db.add(db_session)
        await db.commit()
        await db.refresh(db_session)

        # 8. Track in memory
        self.active_sessions[pty_session.session_id] = pty_session

        # Verify session is tracked in both manager and broker
        assert pty_session.session_id in self.active_sessions, "Session not in manager dict"
        assert pty_session.session_id in self.pty_broker.sessions, "Session not in broker dict"

        logger.info(
            f"Created shell session {pty_session.session_id} for user {user_id}, "
            f"project {project_id}, container {resolved_container_name}. "
            f"Total active sessions: {len(self.active_sessions)}"
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
        user_id: Optional[UUID] = None,
    ) -> None:
        """
        Write data to PTY stdin.

        Args:
            session_id: Session ID to write to
            data: Bytes to write
            db: Database session
            user_id: Optional user ID for authorization check
        """

        # Get session from memory
        session = self.active_sessions.get(session_id)
        if not session:
            # Try to recover session from PTY broker
            session = self.pty_broker.sessions.get(session_id)
            if session:
                logger.warning(f"Session {session_id} found in broker but not in manager, recovering...")
                self.active_sessions[session_id] = session
            else:
                # Check database for session info
                result = await db.execute(
                    select(ShellSession).where(
                        ShellSession.session_id == session_id,
                        ShellSession.status == "active"
                    )
                )
                db_session = result.scalar_one_or_none()
                if db_session:
                    raise ValueError(
                        f"Session {session_id} exists in database but PTY connection is lost. "
                        f"Please close and create a new session."
                    )
                else:
                    raise ValueError(
                        f"Session {session_id} not found. Use shell_open to create a new session."
                    )

        # Authorization check: verify session belongs to requesting user
        if user_id and session.user_id != user_id:
            logger.warning(
                f"User {user_id} attempted to access session {session_id} "
                f"owned by user {session.user_id}"
            )
            raise PermissionError(
                f"Session {session_id} does not belong to the requesting user"
            )

        await self.pty_broker.write_to_pty(session_id, data)

        # Queue stats update for batching (non-blocking)
        # Stats will be flushed periodically by background task
        self.pending_stats_updates.add(session_id)

    async def read_output(
        self,
        session_id: str,
        db: AsyncSession,
        user_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Read new output from session since last read.

        Args:
            session_id: Session ID to read from
            db: Database session
            user_id: Optional user ID for authorization check

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
            # Try to recover session from PTY broker
            session = self.pty_broker.sessions.get(session_id)
            if session:
                logger.warning(f"Session {session_id} found in broker but not in manager, recovering...")
                self.active_sessions[session_id] = session
            else:
                raise ValueError(
                    f"Session {session_id} not found. Use shell_open to create a new session."
                )

        # Authorization check: verify session belongs to requesting user
        if user_id and session.user_id != user_id:
            logger.warning(
                f"User {user_id} attempted to access session {session_id} "
                f"owned by user {session.user_id}"
            )
            raise PermissionError(
                f"Session {session_id} does not belong to the requesting user"
            )

        # Get new output
        new_data, is_eof = await session.read_new_output()

        # Queue stats update for batching (non-blocking)
        # Stats will be flushed periodically by background task
        self.pending_stats_updates.add(session_id)

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

    async def _get_container_name(
        self,
        user_id: UUID,
        project_id: str,
        project_slug: str,
        container_name: Optional[str] = None
    ) -> str:
        """
        Get container/pod name based on deployment mode.

        Args:
            user_id: User ID
            project_id: Project ID
            project_slug: Project slug
            container_name: For Docker multi-container: specific container name to connect to

        Returns:
            The Docker container name or K8s pod name
        """
        from .orchestration import get_orchestrator, is_kubernetes_mode
        orchestrator = get_orchestrator()

        if is_kubernetes_mode():
            # K8s: Deployment names use format "dev-{container_directory}"
            # The container_directory is derived from container name
            if container_name:
                # Sanitize container name same way as helpers.py does
                safe_name = container_name.lower()
                safe_name = safe_name.replace('_', '-').replace(' ', '-').replace('.', '-')
                safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')
                while '--' in safe_name:
                    safe_name = safe_name.replace('--', '-')
                safe_name = safe_name.strip('-')
                return f"dev-{safe_name}"
            else:
                # No container specified - find first running deployment in namespace
                namespace = orchestrator._get_namespace(str(project_id))
                try:
                    # Use correct label selector with tesslate.io prefix
                    pods = await asyncio.to_thread(
                        orchestrator.k8s_client.core_v1.list_namespaced_pod,
                        namespace=namespace,
                        label_selector="tesslate.io/component=dev-container"
                    )
                    if pods.items:
                        # Get deployment name from first dev container pod
                        # Labels use tesslate.io/container-directory
                        container_dir = pods.items[0].metadata.labels.get('tesslate.io/container-directory')
                        if container_dir:
                            return f"dev-{container_dir}"
                        return pods.items[0].metadata.labels.get('app', 'dev')
                except Exception as e:
                    logger.warning(f"Failed to list pods in namespace {namespace}: {e}")
                return "dev"  # Fallback (shouldn't reach here normally)
        else:
            # Docker multi-container mode
            # Container name format: {project_slug}-{service_name}
            if container_name:
                # Sanitize the container name to match docker-compose naming
                # Note: Must match sanitization in projects.py container creation
                sanitized = container_name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
                sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
                sanitized = sanitized.strip('-')
                return f"{project_slug}-{sanitized}"
            else:
                # Default to the first container in the project
                # We'll look this up from the docker-compose file
                status = await orchestrator.get_project_status(project_slug, project_id)

                if status.get('containers'):
                    # Get the first running container, or first container if none running
                    for service_name, info in status['containers'].items():
                        if info.get('running'):
                            return info.get('name', f"{project_slug}-{service_name}")
                    # Fallback to first container
                    first_service = next(iter(status['containers'].keys()))
                    return status['containers'][first_service].get('name', f"{project_slug}-{first_service}")

                raise ValueError(
                    "No containers found for project. Please start the project first."
                )

    async def _is_container_running(
        self,
        user_id: UUID,
        project_id: str,
        project_slug: str,
        container_name: Optional[str] = None
    ) -> bool:
        """
        Check if container/pod is running.

        Args:
            user_id: User ID
            project_id: Project ID
            project_slug: Project slug
            container_name: For Docker multi-container: specific container name to check

        Returns:
            True if the container is running
        """
        from .orchestration import get_orchestrator, is_kubernetes_mode
        orchestrator = get_orchestrator()

        if is_kubernetes_mode():
            # Use orchestrator's is_container_ready method
            status = await orchestrator.is_container_ready(user_id, project_id, container_name)
            return status.get("ready", False)
        else:
            # Docker multi-container mode
            status = await orchestrator.get_project_status(project_slug, project_id)
            logger.info(f"[_is_container_running] project_slug={project_slug}, container_name={container_name}, status={status}")

            if status.get('status') == 'not_found':
                logger.warning(f"[_is_container_running] Project status not found for {project_slug}")
                return False

            if container_name:
                # Check specific container
                # container_name could be:
                # - Full docker name: "project-slug-next-js-15"
                # - Service name: "next-js-15"
                containers = status.get('containers', {})
                logger.info(f"[_is_container_running] Looking for '{container_name}' in containers: {containers}")

                # First try: look up by 'name' field (matches full docker container name)
                for service_name, info in containers.items():
                    if info.get('name') == container_name:
                        logger.info(f"[_is_container_running] Found by name field: running={info.get('running', False)}")
                        return info.get('running', False)

                # Second try: extract service name if full name (project-slug-service)
                if container_name.startswith(f"{project_slug}-"):
                    service_name = container_name[len(project_slug)+1:]
                    container_info = containers.get(service_name)
                    if container_info:
                        logger.info(f"[_is_container_running] Found by extracted service name '{service_name}': running={container_info.get('running', False)}")
                        return container_info.get('running', False)

                # Third try: direct service name lookup
                container_info = containers.get(container_name)
                if container_info:
                    logger.info(f"[_is_container_running] Found by direct lookup: running={container_info.get('running', False)}")
                    return container_info.get('running', False)

                logger.warning(f"[_is_container_running] Container '{container_name}' not found in containers dict")
                return False
            else:
                # Check if any container is running
                for info in status.get('containers', {}).values():
                    if info.get('running'):
                        return True
                return False

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

    async def flush_pending_stats(self, db: AsyncSession) -> int:
        """
        Flush all pending stats updates to database in a single batch.
        This is called periodically to avoid blocking on every keystroke.
        Returns number of sessions updated.
        """
        if not self.pending_stats_updates:
            return 0

        # Get snapshot of pending updates and clear the set
        session_ids_to_update = list(self.pending_stats_updates)
        self.pending_stats_updates.clear()

        updated_count = 0
        for session_id in session_ids_to_update:
            try:
                session = self.active_sessions.get(session_id)
                if not session:
                    continue

                result = await db.execute(
                    select(ShellSession).where(ShellSession.session_id == session_id)
                )
                db_session = result.scalar_one_or_none()
                if db_session:
                    db_session.bytes_read = session.bytes_read
                    db_session.bytes_written = session.bytes_written
                    db_session.last_activity_at = datetime.utcnow()
                    updated_count += 1

            except Exception as e:
                logger.error(f"Failed to update stats for session {session_id}: {e}")
                # Re-queue for next flush attempt
                self.pending_stats_updates.add(session_id)

        if updated_count > 0:
            try:
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to commit stats updates: {e}")
                # Re-queue all for retry
                self.pending_stats_updates.update(session_ids_to_update)

        return updated_count


# Singleton instance
_shell_session_manager = None

def get_shell_session_manager() -> ShellSessionManager:
    """Get singleton shell session manager."""
    global _shell_session_manager
    if _shell_session_manager is None:
        _shell_session_manager = ShellSessionManager()
    return _shell_session_manager
