"""Tesslate Apps runtime router (Wave 3).

Endpoints for session and invocation lifecycle. Authenticates as the
installer of the AppInstance (or a superuser). The plaintext ``api_key``
is returned ONLY in the mint (POST) responses — callers must cache it.

Decimal serialization: ``budget_usd`` is cast to ``float`` with 6-decimal
precision for JSON responses. The DB/service layer uses ``Decimal``; the
router boundary converts at the edges only.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AppInstance
from ..models_auth import User
from ..services.apps import runtime as runtime_svc
from ..services.litellm_service import litellm_service
from ..users import current_active_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas (inline)
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    app_instance_id: UUID
    budget_usd: float = Field(default=1.00, ge=0)
    ttl_seconds: int = Field(default=3600, gt=0)


class InvocationCreateRequest(BaseModel):
    app_instance_id: UUID
    budget_usd: float = Field(default=0.25, ge=0)
    ttl_seconds: int = Field(default=300, gt=0)


class SessionResponse(BaseModel):
    session_id: UUID
    app_instance_id: UUID
    litellm_key_id: str
    api_key: str
    budget_usd: float
    ttl_seconds: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _assert_installer_or_superuser(
    db: AsyncSession, app_instance_id: UUID, user: User
) -> AppInstance:
    instance = (
        await db.execute(
            select(AppInstance).where(AppInstance.id == app_instance_id).limit(1)
        )
    ).scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail="app_instance not found")
    if not user.is_superuser and instance.installer_user_id != user.id:
        raise HTTPException(status_code=403, detail="not the installer")
    return instance


def _to_response(handle: runtime_svc.SessionHandle) -> SessionResponse:
    return SessionResponse(
        session_id=handle.session_id,
        app_instance_id=handle.app_instance_id,
        litellm_key_id=handle.litellm_key_id,
        api_key=handle.api_key,
        budget_usd=round(float(handle.budget_usd), 6),
        ttl_seconds=handle.ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    body: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> SessionResponse:
    await _assert_installer_or_superuser(db, body.app_instance_id, user)
    try:
        handle = await runtime_svc.begin_session(
            db,
            app_instance_id=body.app_instance_id,
            installer_user_id=user.id,
            delegate=litellm_service,
            budget_usd=Decimal(str(body.budget_usd)),
            ttl_seconds=body.ttl_seconds,
        )
    except runtime_svc.AppNotRunnableError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_response(handle)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> Response:
    # Idempotent: runtime.end_session is a no-op for already-settled keys.
    await runtime_svc.end_session(
        db, session_id=session_id, delegate=litellm_service, reason="user_ended"
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Invocations
# ---------------------------------------------------------------------------


@router.post(
    "/invocations",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invocation(
    body: InvocationCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> SessionResponse:
    await _assert_installer_or_superuser(db, body.app_instance_id, user)
    try:
        handle = await runtime_svc.begin_invocation(
            db,
            app_instance_id=body.app_instance_id,
            installer_user_id=user.id,
            delegate=litellm_service,
            budget_usd=Decimal(str(body.budget_usd)),
            ttl_seconds=body.ttl_seconds,
        )
    except runtime_svc.AppNotRunnableError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_response(handle)


@router.delete("/invocations/{session_id}")
async def delete_invocation(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> Response:
    await runtime_svc.end_invocation(
        db, session_id=session_id, delegate=litellm_service
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
