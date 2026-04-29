"""POST /v1/telemetry/install + /v1/telemetry/usage — opt-in telemetry sink."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import TelemetryRecord
from ..schemas import TelemetryAck, TelemetryEvent
from ..services.auth import Principal, get_principal
from ..services.capability_router import requires_capability

router = APIRouter(prefix="/v1", tags=["telemetry"])


async def _record(
    db: AsyncSession,
    event: TelemetryEvent,
    *,
    event_type: str,
) -> TelemetryAck:
    record = TelemetryRecord(
        kind=event.kind,
        slug=event.slug,
        version=event.version,
        event_type=event_type,
        install_id=event.install_id,
        payload=event.payload,
    )
    db.add(record)
    await db.commit()
    return TelemetryAck(received_at=datetime.now(tz=timezone.utc))


@router.post("/telemetry/install", response_model=TelemetryAck, status_code=202)
@requires_capability("telemetry.opt_in")
async def post_install(
    event: TelemetryEvent,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> TelemetryAck:
    principal.require_scope("telemetry.write")
    return await _record(db, event, event_type="install")


@router.post("/telemetry/usage", response_model=TelemetryAck, status_code=202)
@requires_capability("telemetry.opt_in")
async def post_usage(
    event: TelemetryEvent,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> TelemetryAck:
    principal.require_scope("telemetry.write")
    return await _record(db, event, event_type="usage")
