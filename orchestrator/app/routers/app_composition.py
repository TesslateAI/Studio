"""HTTP surface for App Composition (Phase 3).

Exposes three endpoints that mirror :mod:`app.services.apps.composition`:

* ``POST /api/v1/composition/installs/{parent_install_id}/dispatch_via_link/{alias}/{action_name}``
  — parent → child action.
* ``POST /api/v1/composition/installs/{parent_install_id}/mint_embed/{alias}/{view_name}``
  — parent → child view (returns a signed JWT for an iframe src).
* ``GET  /api/v1/composition/installs/{parent_install_id}/data_resource/{alias}/{resource_name}``
  — parent → child data resource (cached dispatch).

Auth model
----------
Mirrors :mod:`app_actions`: the caller must be the parent install's
``installer_user_id``, a superuser, or a team member with PROJECT_EDIT
on the parent's underlying project. Anyone else gets 404 — we do not
leak the existence of an install they cannot see.

Plus the composition gates: ``ActionNotInGrants`` / ``ViewNotInGrants``
/ ``DataResourceNotInGrants`` map to 403; ``AliasNotFound`` maps to 404.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Project, User
from ..models_automations import AppInstance
from ..permissions import (
    Permission,
    get_effective_project_role,
    has_permission,
)
from ..services.apps import composition
from ..services.apps.action_dispatcher import (
    ActionDispatchError,
    ActionDispatchFailed,
    ActionHandlerNotSupported,
    ActionInputInvalid,
    ActionOutputInvalid,
    AppActionNotFound,
    AppInstanceNotFound,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/composition", tags=["apps:composition"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DispatchInput(BaseModel):
    """Body for ``dispatch_via_link``."""

    input: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: UUID | None = None


class DispatchOut(BaseModel):
    """Mirror of :class:`ActionDispatchResult` — string IDs for portability."""

    output: dict[str, Any]
    artifacts: list[UUID]
    spend_usd: float
    duration_seconds: float
    error: str | None = None


class MintEmbedInput(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=300, gt=0, le=3600)


class MintEmbedOut(BaseModel):
    token: str
    expires_at: str  # ISO-8601


class DataResourceQueryOut(BaseModel):
    output: Any
    cached: bool


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


async def _load_parent_with_access(
    db: AsyncSession,
    parent_install_id: UUID,
    user: User,
) -> AppInstance:
    """Return the parent ``AppInstance`` if the caller can compose with it.

    Same access pattern as :func:`app_actions._load_instance_with_access`:
    superusers + installer + team members with PROJECT_EDIT on the
    project. Everyone else gets 404 to avoid leaking install existence.
    """
    inst = await db.get(AppInstance, parent_install_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="app_instance not found")

    if getattr(user, "is_superuser", False):
        return inst
    if inst.installer_user_id == user.id:
        return inst

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
# Error mapping helper — shared between the three endpoints.
# ---------------------------------------------------------------------------


def _map_dispatcher_error(exc: Exception) -> HTTPException:
    """Translate an action-dispatcher exception into an HTTPException.

    Mirrors the mapping in :mod:`app_actions.invoke_action` so cross-app
    calls fail with the same shape as direct invocations.
    """
    if isinstance(exc, AppInstanceNotFound):
        return HTTPException(status_code=404, detail="app_instance not found")
    if isinstance(exc, AppActionNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ActionInputInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ActionOutputInvalid):
        return HTTPException(
            status_code=502, detail=f"action output invalid: {exc}"
        )
    if isinstance(exc, ActionHandlerNotSupported):
        return HTTPException(status_code=501, detail=str(exc))
    if isinstance(exc, ActionDispatchFailed):
        detail: dict[str, Any] = {"message": str(exc)}
        if exc.status is not None:
            detail["upstream_status"] = exc.status
        if exc.body:
            detail["upstream_body"] = exc.body[:1000]
        return HTTPException(status_code=502, detail=detail)
    if isinstance(exc, ActionDispatchError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/installs/{parent_install_id}/dispatch_via_link/{alias}/{action_name}",
    response_model=DispatchOut,
)
async def dispatch_via_link_route(
    parent_install_id: UUID,
    alias: str,
    action_name: str,
    body: DispatchInput | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DispatchOut:
    """Parent → child typed action call. Gated by ``app_instance_links``."""
    body = body or DispatchInput()
    await _load_parent_with_access(db, parent_install_id, user)

    try:
        result = await composition.dispatch_via_link(
            db,
            parent_install_id=parent_install_id,
            alias=alias,
            action_name=action_name,
            input=body.input or {},
            parent_run_id=body.parent_run_id,
        )
    except composition.AliasNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except composition.ActionNotInGrants as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — funnel through dispatcher map
        raise _map_dispatcher_error(exc) from exc

    return DispatchOut(
        output=result.output,
        artifacts=result.artifacts,
        spend_usd=float(result.spend_usd),
        duration_seconds=result.duration_seconds,
        error=result.error,
    )


@router.post(
    "/installs/{parent_install_id}/mint_embed/{alias}/{view_name}",
    response_model=MintEmbedOut,
)
async def mint_embed_route(
    parent_install_id: UUID,
    alias: str,
    view_name: str,
    body: MintEmbedInput | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MintEmbedOut:
    """Mint a signed JWT for embedding the child's view in the parent."""
    body = body or MintEmbedInput()
    await _load_parent_with_access(db, parent_install_id, user)

    try:
        token = await composition.mint_embed_token(
            db,
            parent_install_id=parent_install_id,
            alias=alias,
            view_name=view_name,
            input=body.input or {},
            ttl_seconds=body.ttl_seconds,
            minted_by_user_id=user.id,
        )
    except composition.AliasNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except composition.ViewNotInGrants as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    expires_at = (
        datetime.now(UTC) + timedelta(seconds=body.ttl_seconds)
    ).isoformat()
    return MintEmbedOut(token=token, expires_at=expires_at)


@router.get(
    "/installs/{parent_install_id}/data_resource/{alias}/{resource_name}",
    response_model=DataResourceQueryOut,
)
async def query_data_resource_route(
    parent_install_id: UUID,
    alias: str,
    resource_name: str,
    input_json: str | None = Query(
        default=None,
        alias="input",
        description="JSON-encoded input dict for the data resource query",
    ),
    force_refresh: bool = Query(default=False),
    parent_run_id: UUID | None = Query(default=None),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DataResourceQueryOut:
    """Query a child app's typed data resource, with cache."""
    await _load_parent_with_access(db, parent_install_id, user)

    if input_json:
        try:
            parsed_input = json.loads(input_json)
            if not isinstance(parsed_input, dict):
                raise ValueError("input must be a JSON object")
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid input JSON: {exc}"
            ) from exc
    else:
        parsed_input = {}

    try:
        # We can't tell from the public API whether the result was a
        # cache hit; the simplest accurate signal is `cached=not force_refresh`
        # AND the value came back from the cache path — but exposing that
        # requires a flag in the service. Phase 3 keeps it conservative:
        # report cached=False on force_refresh, otherwise let the field
        # advertise the *intent* (cache eligible) so the UI can render a
        # "fresh" badge if Phase 5 wants one.
        output = await composition.query_data_resource(
            db,
            parent_install_id=parent_install_id,
            alias=alias,
            resource_name=resource_name,
            input=parsed_input,
            parent_run_id=parent_run_id,
            force_refresh=force_refresh,
        )
    except composition.AliasNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except composition.DataResourceNotInGrants as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except composition.CompositionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _map_dispatcher_error(exc) from exc

    return DataResourceQueryOut(output=output, cached=not force_refresh)


__all__ = ["router"]
