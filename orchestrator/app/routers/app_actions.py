"""Direct external invocation of an installed app's typed actions.

Surfaces the Phase 1 ``services.apps.action_dispatcher.dispatch_app_action``
entry point as a stable HTTP endpoint that external API clients (and, in
later waves, the gateway slash-command handler) can hit without going
through the Automation Runtime.

Auth model
----------
Two paths accepted:

* Session JWT (``current_active_user``) — caller must be the install's
  ``installer_user_id`` OR a team member with PROJECT_EDIT on the install's
  underlying project. Mirrors :mod:`app_installs` ``get_install_detail`` so
  the same 404-on-no-access pattern applies.
* External API key (``require_api_scope``) — falls through the same auth dep
  because the ``current_active_user`` chain transparently accepts API-key
  bearers; we then enforce ``Permission.AGENT_MANAGE`` at the access check
  for write operations. (Phase 1 reuses AGENT_MANAGE; a dedicated
  ``app.invoke`` permission will be added in a later wave once external
  clients ship.)

Endpoints
---------

* ``POST /api/apps/{app_instance_id}/actions/{action_name}`` — invoke.
* ``GET  /api/apps/{app_instance_id}/actions``                 — list.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Project, User
from ..models_automations import AppAction, AppInstance
from ..permissions import (
    Permission,
    get_effective_project_role,
    has_permission,
)
from ..schemas_automations import (
    AppActionInvokeRequest,
    AppActionInvokeResponse,
    AppActionListResponse,
    AppActionRow,
)
from ..services.apps.action_dispatcher import (
    ActionDispatchError,
    ActionDispatchFailed,
    ActionHandlerNotSupported,
    ActionInputInvalid,
    ActionOutputInvalid,
    AppActionNotFound,
    AppInstanceNotFound,
    dispatch_app_action,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/apps", tags=["apps:actions"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def _load_instance_with_access(
    db: AsyncSession,
    app_instance_id: UUID,
    user: User,
) -> AppInstance:
    """Return the AppInstance if the caller can invoke actions on it.

    Owner (installer_user_id), superusers, and team members with
    PROJECT_EDIT on the install's underlying project are allowed. Anyone
    else gets 404 (do not leak the existence of an install they cannot
    see — same rule as :func:`app_installs.get_install_detail`).
    """
    inst = (
        await db.execute(
            select(AppInstance).where(AppInstance.id == app_instance_id)
        )
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(status_code=404, detail="app_instance not found")

    if getattr(user, "is_superuser", False):
        return inst
    if inst.installer_user_id == user.id:
        return inst

    # Team-membership path.
    if inst.project_id is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    project = await db.get(Project, inst.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    role = await get_effective_project_role(db, project, user.id)
    if role is None or not has_permission(role, Permission.PROJECT_EDIT):
        raise HTTPException(status_code=404, detail="app_instance not found")
    return inst


# ---------------------------------------------------------------------------
# Invoke
# ---------------------------------------------------------------------------


@router.post(
    "/{app_instance_id}/actions/{action_name}",
    response_model=AppActionInvokeResponse,
)
async def invoke_action(
    app_instance_id: UUID,
    action_name: str,
    payload: AppActionInvokeRequest | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AppActionInvokeResponse:
    """Invoke a typed action on an installed app.

    The dispatcher validates ``input`` against the action's ``input_schema``
    and the resulting ``output`` against ``output_schema``. Schema
    violations surface as 400; missing instance / action as 404; tenancy
    or handler-kind issues as 501; transport / handler errors as 502.
    """
    payload = payload or AppActionInvokeRequest()

    inst = await _load_instance_with_access(db, app_instance_id, user)

    try:
        result = await dispatch_app_action(
            db,
            app_instance_id=inst.id,
            action_name=action_name,
            input=payload.input or {},
            run_id=None,
        )
    except AppInstanceNotFound:
        # We resolved the instance above, so this can only mean a race
        # with uninstall. Treat as 404.
        raise HTTPException(status_code=404, detail="app_instance not found") from None
    except AppActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionInputInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ActionOutputInvalid as exc:
        # Creator bug — surface as 502 (bad gateway). The caller did
        # nothing wrong; the app's handler did.
        raise HTTPException(
            status_code=502, detail=f"action output invalid: {exc}"
        ) from exc
    except ActionHandlerNotSupported as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ActionDispatchFailed as exc:
        # Transport / handler failure. Include status + truncated body so
        # the caller can debug without a roundtrip to logs.
        detail = {"message": str(exc)}
        if exc.status is not None:
            detail["upstream_status"] = exc.status
        if exc.body:
            detail["upstream_body"] = exc.body[:1000]
        raise HTTPException(status_code=502, detail=detail) from exc
    except ActionDispatchError as exc:  # safety net for new subclasses
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info(
        "[APP-ACTIONS] invoke instance=%s action=%s by user=%s artifacts=%d "
        "duration=%.3fs",
        inst.id,
        action_name,
        user.id,
        len(result.artifacts),
        result.duration_seconds,
    )

    return AppActionInvokeResponse(
        output=result.output,
        artifacts=result.artifacts,
        spend_usd=result.spend_usd,
        duration_seconds=result.duration_seconds,
        error=result.error,
    )


# ---------------------------------------------------------------------------
# List actions for an install
# ---------------------------------------------------------------------------


@router.get(
    "/{app_instance_id}/actions", response_model=AppActionListResponse
)
async def list_actions(
    app_instance_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AppActionListResponse:
    """Return every action declared by the install's pinned AppVersion.

    Schemas are returned verbatim so the caller can render forms / build a
    typed client without re-fetching the manifest.
    """
    inst = await _load_instance_with_access(db, app_instance_id, user)

    rows = (
        (
            await db.execute(
                select(AppAction)
                .where(AppAction.app_version_id == inst.app_version_id)
                .order_by(AppAction.name.asc())
            )
        )
        .scalars()
        .all()
    )

    return AppActionListResponse(
        app_instance_id=inst.id,
        app_version_id=inst.app_version_id,
        actions=[AppActionRow.model_validate(r) for r in rows],
    )


__all__ = ["router"]
