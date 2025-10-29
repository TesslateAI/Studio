from uuid import UUID
"""
Audit logging service for agent command executions.

This module provides audit trail functionality for all agent commands,
logging execution details to the database for security and compliance.
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from ..models import AgentCommandLog, User, Project

logger = logging.getLogger(__name__)


class AgentAuditService:
    """
    Service for auditing agent command executions.

    Provides methods to log commands, query audit history, and detect
    suspicious patterns that may indicate security issues.
    """

    def __init__(self, db: AsyncSession):
        """Initialize audit service with database session."""
        self.db = db

    async def log_command(
        self,
        user_id: UUID,
        project_id: str,
        command: str,
        working_dir: str = ".",
        success: bool = False,
        exit_code: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        duration_ms: Optional[int] = None,
        risk_level: str = "safe",
        dry_run: bool = False
    ) -> AgentCommandLog:
        """
        Log an agent command execution to the database.

        Args:
            user_id: ID of the user who executed the command
            project_id: ID of the project the command was executed in
            command: The command that was executed
            working_dir: Working directory for command execution
            success: Whether the command succeeded
            exit_code: Command exit code
            stdout: Standard output from command
            stderr: Standard error from command
            duration_ms: Execution duration in milliseconds
            risk_level: Risk level (safe, moderate, high)
            dry_run: Whether this was a dry-run (simulation)

        Returns:
            The created AgentCommandLog entry
        """
        # Truncate output if too long (prevent database bloat)
        max_output_length = 10000
        if stdout and len(stdout) > max_output_length:
            stdout = stdout[:max_output_length] + "\n...[truncated]"
        if stderr and len(stderr) > max_output_length:
            stderr = stderr[:max_output_length] + "\n...[truncated]"

        log_entry = AgentCommandLog(
            user_id=user_id,
            project_id=project_id,
            command=command,
            working_dir=working_dir,
            success=success,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            risk_level=risk_level,
            dry_run=dry_run
        )

        self.db.add(log_entry)
        await self.db.commit()
        await self.db.refresh(log_entry)

        logger.info(
            f"Logged agent command for user {user_id}, project {project_id}: "
            f"{command[:50]}... success={success}, risk={risk_level}"
        )

        return log_entry

    async def get_user_command_history(
        self,
        user_id: UUID,
        project_id: Optional[UUID] = None,
        limit: int = 100,
        include_dry_run: bool = False
    ) -> list[AgentCommandLog]:
        """
        Get command history for a user.

        Args:
            user_id: User ID to query
            project_id: Optional project ID to filter by
            limit: Maximum number of entries to return
            include_dry_run: Whether to include dry-run commands

        Returns:
            List of AgentCommandLog entries
        """
        query = select(AgentCommandLog).where(AgentCommandLog.user_id == user_id)

        if project_id is not None:
            query = query.where(AgentCommandLog.project_id == project_id)

        if not include_dry_run:
            query = query.where(AgentCommandLog.dry_run == False)

        query = query.order_by(AgentCommandLog.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_command_stats(self, user_id: UUID, days: int = 7) -> dict:
        """
        Get command execution statistics for a user.

        Args:
            user_id: User ID to query
            days: Number of days to look back

        Returns:
            Dictionary with statistics
        """
        since = datetime.utcnow() - timedelta(days=days)

        # Total commands
        total_query = select(func.count(AgentCommandLog.id)).where(
            AgentCommandLog.user_id == user_id,
            AgentCommandLog.created_at >= since,
            AgentCommandLog.dry_run == False
        )
        total_result = await self.db.execute(total_query)
        total_commands = total_result.scalar()

        # Successful commands
        success_query = select(func.count(AgentCommandLog.id)).where(
            AgentCommandLog.user_id == user_id,
            AgentCommandLog.created_at >= since,
            AgentCommandLog.success == True,
            AgentCommandLog.dry_run == False
        )
        success_result = await self.db.execute(success_query)
        successful_commands = success_result.scalar()

        # High risk commands
        high_risk_query = select(func.count(AgentCommandLog.id)).where(
            AgentCommandLog.user_id == user_id,
            AgentCommandLog.created_at >= since,
            AgentCommandLog.risk_level == "high",
            AgentCommandLog.dry_run == False
        )
        high_risk_result = await self.db.execute(high_risk_query)
        high_risk_commands = high_risk_result.scalar()

        # Average duration
        avg_duration_query = select(func.avg(AgentCommandLog.duration_ms)).where(
            AgentCommandLog.user_id == user_id,
            AgentCommandLog.created_at >= since,
            AgentCommandLog.dry_run == False,
            AgentCommandLog.duration_ms.isnot(None)
        )
        avg_duration_result = await self.db.execute(avg_duration_query)
        avg_duration = avg_duration_result.scalar() or 0

        return {
            "total_commands": total_commands or 0,
            "successful_commands": successful_commands or 0,
            "failed_commands": (total_commands or 0) - (successful_commands or 0),
            "high_risk_commands": high_risk_commands or 0,
            "average_duration_ms": int(avg_duration),
            "period_days": days
        }

    async def detect_suspicious_activity(
        self,
        user_id: UUID,
        time_window_minutes: int = 5
    ) -> dict:
        """
        Detect suspicious command patterns that may indicate security issues.

        Checks for:
        - Rapid command execution (potential automation attack)
        - High failure rate
        - Unusual number of file deletions
        - Repeated high-risk commands

        Args:
            user_id: User ID to check
            time_window_minutes: Time window to analyze

        Returns:
            Dictionary with alert information
        """
        since = datetime.utcnow() - timedelta(minutes=time_window_minutes)

        query = select(AgentCommandLog).where(
            AgentCommandLog.user_id == user_id,
            AgentCommandLog.created_at >= since,
            AgentCommandLog.dry_run == False
        )

        result = await self.db.execute(query)
        recent_commands = result.scalars().all()

        alerts = []

        # Check for rapid execution (rate limiting)
        if len(recent_commands) > 50:
            alerts.append({
                "type": "rapid_execution",
                "severity": "high",
                "message": f"User executed {len(recent_commands)} commands in {time_window_minutes} minutes",
                "count": len(recent_commands)
            })

        # Check for high failure rate
        if len(recent_commands) >= 10:
            failed_count = sum(1 for cmd in recent_commands if not cmd.success)
            failure_rate = failed_count / len(recent_commands)
            if failure_rate > 0.5:
                alerts.append({
                    "type": "high_failure_rate",
                    "severity": "medium",
                    "message": f"High failure rate: {failure_rate:.1%} of commands failed",
                    "failure_rate": failure_rate
                })

        # Check for excessive file deletions
        deletion_commands = [
            cmd for cmd in recent_commands
            if "rm" in cmd.command.lower()
        ]
        if len(deletion_commands) > 10:
            alerts.append({
                "type": "excessive_deletions",
                "severity": "high",
                "message": f"User executed {len(deletion_commands)} file deletion commands",
                "count": len(deletion_commands)
            })

        # Check for repeated high-risk commands
        high_risk_commands = [
            cmd for cmd in recent_commands
            if cmd.risk_level == "high"
        ]
        if len(high_risk_commands) > 5:
            alerts.append({
                "type": "high_risk_activity",
                "severity": "high",
                "message": f"User executed {len(high_risk_commands)} high-risk commands",
                "count": len(high_risk_commands)
            })

        if alerts:
            logger.warning(
                f"Suspicious activity detected for user {user_id}: "
                f"{len(alerts)} alerts in {time_window_minutes} minutes"
            )

        return {
            "user_id": user_id,
            "time_window_minutes": time_window_minutes,
            "total_commands": len(recent_commands),
            "alerts": alerts,
            "is_suspicious": len(alerts) > 0
        }


def get_audit_service(db: AsyncSession) -> AgentAuditService:
    """Create an audit service instance with the given database session."""
    return AgentAuditService(db)
