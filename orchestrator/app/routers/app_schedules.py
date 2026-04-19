"""Per-schedule webhook secret management endpoints.

Provides rotate / revoke / list operations on the kid-keyed
``trigger_config["webhook_secrets"]`` array maintained by the installer
(``services/apps/installer.py``) and verified by ``routers/app_triggers``.

Auth model mirrors ``app_runtime_status``: the AppInstance installer or any
project editor (owner / admin / editor). Plaintext secrets are returned ONLY
on rotate, and only once — they are never re-derivable from list responses.

Rotation is rate-limited to keep accidental loops or compromised tokens from
flooding the secrets array.
"""

from __future__ import annotations

import logging
import secrets as _secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..database import get_db
from ..models import AgentSchedule, AppInstance, Project, User
from ..permissions import Permission, get_effective_project_role, has_permission
from ..services.audit_service import log_event
from ..services.rate_limit import rate_limited
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Schemas ---------------------------------------------------------------


class WebhookSecretListItem(BaseModel):
    kid: str
    created_at: str | None = None
    revoked_at: str | None = None


class WebhookSecretRotated(BaseModel):
    kid: str
    secret: str  # Plaintext, returned ONCE.
    created_at: str


class WebhookSecretRevoked(BaseModel):
    kid: str
    revoked_at: str


# --- Helpers ---------------------------------------------------------------


async def _load_instance(db: AsyncSession, instance_id: UUID) -> AppInstance:
    inst = (
        await db.execute(select(AppInstance).where(AppInstance.id == instance_id))
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    if inst.project_id is None:
        raise HTTPException(
            status_code=409,
            detail="app_instance has no project (uninstalled?)",
        )
    return inst


async def _authorize(db: AsyncSession, inst: AppInstance, user: User) -> Project:
    project = await db.get(Project, inst.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if inst.installer_user_id == user.id or getattr(user, "is_superuser", False):
        return project
    role = await get_effective_project_role(db, project, user.id)
    if role is None or not has_permission(role, Permission.PROJECT_EDIT):
        # Same opaque 404 shape used by app_runtime_status.
        raise HTTPException(status_code=404, detail="app_instance not found")
    return project


async def _load_webhook_schedule(
    db: AsyncSession, instance_id: UUID, schedule_id: UUID
) -> AgentSchedule:
    sched = (
        await db.execute(
            select(AgentSchedule).where(
                AgentSchedule.id == schedule_id,
                AgentSchedule.app_instance_id == instance_id,
            )
        )
    ).scalar_one_or_none()
    if sched is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    if sched.trigger_kind != "webhook":
        raise HTTPException(
            status_code=409,
            detail="schedule is not a webhook trigger",
        )
    return sched


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_secrets_list(trig_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Coerce trigger_config into the new list shape, lifting a legacy
    ``webhook_secret`` string into a ``v1`` entry on the way through. Returns
    a fresh list — caller assigns it back into ``trig_cfg``.
    """
    raw = trig_cfg.get("webhook_secrets")
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for entry in raw:
            if isinstance(entry, dict) and entry.get("secret"):
                out.append(
                    {
                        "kid": str(entry.get("kid") or ""),
                        "secret": str(entry["secret"]),
                        "created_at": entry.get("created_at"),
                        "revoked_at": entry.get("revoked_at"),
                    }
                )
        return out
    legacy = trig_cfg.get("webhook_secret")
    if isinstance(legacy, str) and legacy:
        return [
            {
                "kid": "v1",
                "secret": legacy,
                "created_at": None,
                "revoked_at": None,
            }
        ]
    return []


def _next_kid(existing: list[dict[str, Any]]) -> str:
    """Pick the next ``v{N+1}`` kid by scanning the existing ``v\\d+`` ones.

    Non-conforming kids (e.g. ``legacy``) are ignored for numbering, which
    means a legacy upgrade still produces ``v2`` after migration as if a real
    ``v1`` had existed.
    """
    max_n = 0
    for entry in existing:
        kid = str(entry.get("kid") or "")
        if kid.startswith("v") and kid[1:].isdigit():
            n = int(kid[1:])
            if n > max_n:
                max_n = n
    return f"v{max_n + 1}"


# --- Endpoints -------------------------------------------------------------


@router.get(
    "/{install_id}/schedules/{schedule_id}/webhook",
    response_model=list[WebhookSecretListItem],
)
async def list_webhook_secrets(
    install_id: UUID,
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> list[WebhookSecretListItem]:
    inst = await _load_instance(db, install_id)
    await _authorize(db, inst, user)
    sched = await _load_webhook_schedule(db, install_id, schedule_id)

    items = _normalize_secrets_list(dict(sched.trigger_config or {}))
    return [
        WebhookSecretListItem(
            kid=e["kid"],
            created_at=e.get("created_at"),
            revoked_at=e.get("revoked_at"),
        )
        for e in items
    ]


@router.post(
    "/{install_id}/schedules/{schedule_id}/webhook/rotate",
    response_model=WebhookSecretRotated,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_webhook_secret(
    install_id: UUID,
    schedule_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    # 5 rotations per hour per user is a generous cap that still throttles
    # accidental loops without blocking legitimate emergency rotations.
    user: User = Depends(
        rate_limited(
            "webhook_secret_rotate",
            capacity=5,
            window_seconds=3600,
            audit_action="webhook_secret_rotate_rate_limited",
        )
    ),
) -> WebhookSecretRotated:
    inst = await _load_instance(db, install_id)
    project = await _authorize(db, inst, user)
    sched = await _load_webhook_schedule(db, install_id, schedule_id)

    trig_cfg = dict(sched.trigger_config or {})
    secrets_list = _normalize_secrets_list(trig_cfg)

    new_kid = _next_kid(secrets_list)
    new_secret = _secrets.token_urlsafe(32)
    created_at = _now_iso()
    secrets_list.append(
        {
            "kid": new_kid,
            "secret": new_secret,
            "created_at": created_at,
            "revoked_at": None,
        }
    )
    trig_cfg["webhook_secrets"] = secrets_list
    # Drop the legacy single-key field on first rotation so future reads stop
    # picking it up via fallback.
    trig_cfg.pop("webhook_secret", None)
    sched.trigger_config = trig_cfg
    flag_modified(sched, "trigger_config")

    try:
        await log_event(
            db=db,
            team_id=project.team_id,
            user_id=user.id,
            action="webhook_secret_rotated",
            resource_type="agent_schedule",
            resource_id=sched.id,
            project_id=project.id,
            details={"kid": new_kid, "instance_id": str(install_id)},
            request=request,
        )
    except Exception:
        logger.exception("app_schedules: rotate audit failed (non-blocking)")

    await db.commit()

    return WebhookSecretRotated(kid=new_kid, secret=new_secret, created_at=created_at)


@router.post(
    "/{install_id}/schedules/{schedule_id}/webhook/revoke/{kid}",
    response_model=WebhookSecretRevoked,
)
async def revoke_webhook_secret(
    install_id: UUID,
    schedule_id: UUID,
    kid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> WebhookSecretRevoked:
    inst = await _load_instance(db, install_id)
    project = await _authorize(db, inst, user)
    sched = await _load_webhook_schedule(db, install_id, schedule_id)

    trig_cfg = dict(sched.trigger_config or {})
    secrets_list = _normalize_secrets_list(trig_cfg)
    target = next((e for e in secrets_list if e["kid"] == kid), None)
    if target is None:
        raise HTTPException(status_code=404, detail="kid not found")
    if target.get("revoked_at"):
        # Idempotent: return the existing revocation timestamp.
        return WebhookSecretRevoked(kid=kid, revoked_at=str(target["revoked_at"]))

    # Refuse to revoke the last live secret — would brick the trigger. Callers
    # should rotate first, then revoke.
    live = [e for e in secrets_list if not e.get("revoked_at")]
    if len(live) <= 1:
        raise HTTPException(
            status_code=409,
            detail="cannot revoke the only live secret; rotate first",
        )

    revoked_at = _now_iso()
    target["revoked_at"] = revoked_at
    trig_cfg["webhook_secrets"] = secrets_list
    trig_cfg.pop("webhook_secret", None)
    sched.trigger_config = trig_cfg
    flag_modified(sched, "trigger_config")

    try:
        await log_event(
            db=db,
            team_id=project.team_id,
            user_id=user.id,
            action="webhook_secret_revoked",
            resource_type="agent_schedule",
            resource_id=sched.id,
            project_id=project.id,
            details={"kid": kid, "instance_id": str(install_id)},
            request=request,
        )
    except Exception:
        logger.exception("app_schedules: revoke audit failed (non-blocking)")

    await db.commit()

    return WebhookSecretRevoked(kid=kid, revoked_at=revoked_at)
