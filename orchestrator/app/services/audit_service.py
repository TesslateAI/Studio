"""
Non-blocking audit trail service.
Fires and forgets — audit logging NEVER blocks the primary operation.
On failure, logs to stderr but does not raise.
"""
import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models_team import AuditLog

logger = logging.getLogger(__name__)


async def log_event(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    project_id: UUID | None = None,
    details: dict | None = None,
    request: Request | None = None,
):
    """
    Non-blocking audit log entry.
    On failure, logs error but does not raise.
    """
    try:
        ip_address = None
        user_agent = None
        if request:
            ip_address = request.client.host if request.client else None
            ua = request.headers.get("user-agent", "")
            user_agent = ua[:500] if ua else None

        entry = AuditLog(
            team_id=team_id,
            project_id=project_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        await db.flush()
    except Exception:
        logger.exception("Failed to write audit log entry (non-blocking)")


async def cleanup_expired_audit_logs(db: AsyncSession, retention_days: int = 90):
    """Delete audit log entries older than retention period. Called by background cron."""
    from datetime import UTC, datetime, timedelta

    try:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await db.commit()
        logger.info(f"Cleaned up audit logs older than {retention_days} days")
    except Exception:
        logger.exception("Failed to cleanup expired audit logs")
