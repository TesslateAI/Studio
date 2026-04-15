"""Thin audit logger for Tesslate Apps events.

Wraps the existing AuditLog model in `app.models_team`. The schema requires
`team_id` and `user_id` to be NOT NULL, so when either is missing we fall
back to a logger-only emission (no DB row). This keeps the caller API flexible
(public-app events may be actor-less) without blocking progress — a dedicated
`app_audit_logs` table can replace this wrapper in a future wave.

This function is best-effort: DB errors NEVER propagate to the caller.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


try:
    from ...models_team import AuditLog
    _AUDIT_LOG_AVAILABLE = True
except Exception:  # pragma: no cover
    AuditLog = None  # type: ignore[assignment]
    _AUDIT_LOG_AVAILABLE = False


async def write_audit(
    db: AsyncSession,
    *,
    actor_user_id: UUID | None,
    team_id: UUID | None,
    project_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    """Insert an AuditLog row. Never raises on failure."""
    logger.info(
        "AUDIT action=%s resource_type=%s resource_id=%s actor=%s team=%s project=%s details=%s",
        action, resource_type, resource_id, actor_user_id, team_id, project_id, details,
    )

    if not _AUDIT_LOG_AVAILABLE:
        return
    # AuditLog requires team_id + user_id NOT NULL — skip DB write for
    # app-level events without a team/actor (still logged above).
    if team_id is None or actor_user_id is None:
        return

    try:
        resource_uuid: UUID | None
        try:
            resource_uuid = UUID(str(resource_id))
        except (ValueError, TypeError):
            resource_uuid = None

        row = AuditLog(
            team_id=team_id,
            project_id=project_id,
            user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_uuid,
            details=details or {},
        )
        db.add(row)
        await db.flush()
    except Exception:
        logger.warning("audit.write_audit: failed to persist audit row", exc_info=True)
