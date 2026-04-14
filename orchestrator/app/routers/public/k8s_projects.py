"""
Authenticated cloud runtime endpoints for the desktop client.

All endpoints delegate to the unified `BaseOrchestrator` via
`services.orchestration.get_orchestrator()`; there are no conditional
branches between the Docker and Kubernetes backends here. The prefix
reflects the historical PRD naming (`/k8s/projects`), but the surface
operates identically regardless of `DEPLOYMENT_MODE`.

- `POST   /api/v1/k8s/projects`                        — start (create-or-start)
- `GET    /api/v1/k8s/projects/{slug}`                 — status
- `POST   /api/v1/k8s/projects/{slug}/start|stop|restart`
- `DELETE /api/v1/k8s/projects/{slug}`                 — stop + release
- `GET    /api/v1/k8s/projects/{slug}/events`          — SSE status poll
- `GET    /api/v1/k8s/projects/{slug}/logs/{container}`— SSE log stream
- `WS     /api/v1/k8s/projects/{slug}/exec`            — non-interactive exec
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import hashlib
from datetime import UTC, datetime

from ...database import AsyncSessionLocal, get_db
from ...models import ExternalAPIKey
from ...models import Container, ContainerConnection, User
from ...permissions import Permission, get_project_with_access
from ...services.orchestration import get_orchestrator
from ._deps import audit_write, scoped

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = Permission.K8S_PROJECTS

router = APIRouter(prefix="/api/v1/k8s/projects", tags=["public-k8s-projects"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class StartRequest(BaseModel):
    project_id: UUID


class LifecycleResponse(BaseModel):
    project_slug: str
    status: str
    containers: dict[str, Any] = {}
    namespace: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_topology(db: AsyncSession, project_id: UUID):
    containers = list((
        await db.execute(
            select(Container)
            .where(Container.project_id == project_id)
            .options(selectinload(Container.base))
        )
    ).scalars().all())
    connections = list((
        await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project_id)
        )
    ).scalars().all())
    return containers, connections


def _lifecycle_payload(project_slug: str, result: dict) -> dict:
    return {
        "project_slug": project_slug,
        "status": result.get("status", "unknown"),
        "containers": result.get("containers", {}),
        "namespace": result.get("namespace"),
    }


# ---------------------------------------------------------------------------
# Lifecycle endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=LifecycleResponse)
async def create_or_start(
    body: StartRequest,
    user: User = Depends(scoped(Permission.K8S_PROJECTS, rate_cost=5)),
    db: AsyncSession = Depends(get_db),
) -> LifecycleResponse:
    project, _role = await get_project_with_access(
        db, str(body.project_id), user.id, Permission.CONTAINER_START_STOP
    )
    containers, connections = await _load_topology(db, project.id)
    if not containers:
        raise HTTPException(status_code=400, detail="Project has no containers")

    orchestrator = get_orchestrator()
    result = await orchestrator.start_project(project, containers, connections, user.id, db)

    await audit_write(
        db=db,
        user=user,
        action="k8s_project.start",
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
    )
    return LifecycleResponse(**_lifecycle_payload(project.slug, result))


@router.get("/{project_slug}")
async def get_status(
    project_slug: str,
    user: User = Depends(scoped(Permission.K8S_PROJECTS)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.PROJECT_VIEW
    )
    orchestrator = get_orchestrator()
    status = await orchestrator.get_project_status(project.slug, project.id)
    return {"project_slug": project.slug, "status": status}


@router.post("/{project_slug}/start", response_model=LifecycleResponse)
async def start(
    project_slug: str,
    user: User = Depends(scoped(Permission.K8S_PROJECTS, rate_cost=5)),
    db: AsyncSession = Depends(get_db),
) -> LifecycleResponse:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.CONTAINER_START_STOP
    )
    containers, connections = await _load_topology(db, project.id)
    orchestrator = get_orchestrator()
    result = await orchestrator.start_project(project, containers, connections, user.id, db)
    await audit_write(
        db=db, user=user, action="k8s_project.start",
        resource_type="project", resource_id=project.id, project_id=project.id,
    )
    return LifecycleResponse(**_lifecycle_payload(project.slug, result))


@router.post("/{project_slug}/stop")
async def stop(
    project_slug: str,
    user: User = Depends(scoped(Permission.K8S_PROJECTS, rate_cost=5)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.CONTAINER_START_STOP
    )
    orchestrator = get_orchestrator()
    await orchestrator.stop_project(project.slug, project.id, user.id)
    await audit_write(
        db=db, user=user, action="k8s_project.stop",
        resource_type="project", resource_id=project.id, project_id=project.id,
    )
    return {"project_slug": project.slug, "status": "stopped"}


@router.post("/{project_slug}/restart", response_model=LifecycleResponse)
async def restart(
    project_slug: str,
    user: User = Depends(scoped(Permission.K8S_PROJECTS, rate_cost=10)),
    db: AsyncSession = Depends(get_db),
) -> LifecycleResponse:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.CONTAINER_START_STOP
    )
    containers, connections = await _load_topology(db, project.id)
    orchestrator = get_orchestrator()
    result = await orchestrator.restart_project(project, containers, connections, user.id, db)
    await audit_write(
        db=db, user=user, action="k8s_project.restart",
        resource_type="project", resource_id=project.id, project_id=project.id,
    )
    return LifecycleResponse(**_lifecycle_payload(project.slug, result))


@router.delete("/{project_slug}")
async def delete_runtime(
    project_slug: str,
    user: User = Depends(scoped(Permission.K8S_PROJECTS, rate_cost=5)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.PROJECT_DELETE
    )
    orchestrator = get_orchestrator()
    # Stop, then call backend-specific namespace removal if available.
    await orchestrator.stop_project(project.slug, project.id, user.id)
    teardown = getattr(orchestrator, "delete_project_namespace", None)
    if callable(teardown):
        try:
            await teardown(project.id, user.id)
        except Exception:
            logger.debug("teardown failed for %s", project.slug, exc_info=True)
    await audit_write(
        db=db, user=user, action="k8s_project.delete_runtime",
        resource_type="project", resource_id=project.id, project_id=project.id,
    )
    return {"project_slug": project.slug, "status": "released"}


# ---------------------------------------------------------------------------
# SSE — status events
# ---------------------------------------------------------------------------


async def _status_event_stream(orchestrator, project_slug: str, project_id: UUID, interval: float):
    last_payload: str | None = None
    cursor = 0
    try:
        while True:
            try:
                status = await orchestrator.get_project_status(project_slug, project_id)
            except Exception as exc:  # pragma: no cover — defensive
                status = {"status": "error", "error": str(exc)}
            payload = json.dumps({"cursor": cursor, "status": status})
            if payload != last_payload:
                last_payload = payload
                yield f"id: {cursor}\ndata: {payload}\n\n"
                cursor += 1
            await asyncio.sleep(interval)
    except (asyncio.CancelledError, GeneratorExit):
        return


@router.get("/{project_slug}/events")
async def stream_events(
    project_slug: str,
    interval: float = Query(default=2.0, ge=0.5, le=30.0),
    user: User = Depends(scoped(Permission.K8S_PROJECTS)),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.PROJECT_VIEW
    )
    orchestrator = get_orchestrator()
    return StreamingResponse(
        _status_event_stream(orchestrator, project.slug, project.id, interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# SSE — container logs
# ---------------------------------------------------------------------------


async def _log_event_stream(orchestrator, project_id: UUID, user_id: UUID, container_id: UUID | None, tail: int):
    cursor = 0
    try:
        async for line in orchestrator.stream_logs(
            project_id=project_id, user_id=user_id, container_id=container_id, tail_lines=tail,
        ):
            payload = json.dumps({"cursor": cursor, "line": line})
            yield f"id: {cursor}\ndata: {payload}\n\n"
            cursor += 1
    except (asyncio.CancelledError, GeneratorExit):
        return


@router.get("/{project_slug}/logs/{container_name}")
async def stream_container_logs(
    project_slug: str,
    container_name: str,
    tail: int = Query(default=100, ge=0, le=5000),
    user: User = Depends(scoped(Permission.K8S_PROJECTS)),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    project, _role = await get_project_with_access(
        db, project_slug, user.id, Permission.PROJECT_VIEW
    )
    container = (
        await db.execute(
            select(Container).where(
                Container.project_id == project.id,
                Container.name == container_name,
            )
        )
    ).scalar_one_or_none()
    if container is None:
        raise HTTPException(status_code=404, detail="Container not found")

    orchestrator = get_orchestrator()
    return StreamingResponse(
        _log_event_stream(orchestrator, project.id, user.id, container.id, tail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# WS — non-interactive exec
# ---------------------------------------------------------------------------
# Desktop sends one JSON frame per command: {"container": str, "command": [..],
# "timeout": int?, "working_dir": str?}. We reply with a single frame:
# {"stdout": str, "exit_code": int}. This is deliberately command-scoped, not
# a pty: mirrors existing external tool plumbing without opening a new
# long-lived interactive surface.


async def _authenticate_ws_api_key(token: str, scope: Permission) -> User:
    """Resolve a `tsk_` token on a WebSocket handshake. Mirrors
    `require_api_scope` gate-1 (key scope) — gate-2 (role ceiling) is
    deferred to the per-request surface; WS connections are short-lived and
    bound to a single project that's re-checked via `get_project_with_access`."""
    raw = token[7:] if token.startswith("Bearer ") else token
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    async with AsyncSessionLocal() as db:
        key = (
            await db.execute(
                select(ExternalAPIKey).where(
                    ExternalAPIKey.key_hash == key_hash,
                    ExternalAPIKey.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        if key.expires_at and key.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="API key expired")
        if key.scopes is not None and scope.value not in key.scopes:
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope.value}")
        user = (await db.execute(select(User).where(User.id == key.user_id))).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="User inactive")
        user._api_key_record = key  # type: ignore[attr-defined]
        return user


@router.websocket("/{project_slug}/exec")
async def exec_ws(websocket: WebSocket, project_slug: str):
    await websocket.accept()
    token = websocket.query_params.get("token") or websocket.headers.get("authorization", "")
    if not token:
        await websocket.send_json({"error": "token required"})
        await websocket.close(code=4401)
        return
    try:
        user = await _authenticate_ws_api_key(token, Permission.K8S_PROJECTS)
    except HTTPException as exc:
        await websocket.send_json({"error": exc.detail})
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        try:
            project, _role = await get_project_with_access(
                db, project_slug, user.id, Permission.PROJECT_EDIT
            )
        except HTTPException as exc:
            await websocket.send_json({"error": exc.detail})
            await websocket.close(code=4403)
            return

    orchestrator = get_orchestrator()
    try:
        while True:
            frame = await websocket.receive_json()
            container_name = frame.get("container")
            command = frame.get("command")
            if not container_name or not isinstance(command, list):
                await websocket.send_json({"error": "container and command[] required"})
                continue
            try:
                output = await orchestrator.execute_command(
                    user_id=user.id,
                    project_id=project.id,
                    container_name=container_name,
                    command=command,
                    timeout=int(frame.get("timeout", 120)),
                    working_dir=frame.get("working_dir"),
                )
                await websocket.send_json({"stdout": output, "exit_code": 0})
            except Exception as exc:  # noqa: BLE001
                await websocket.send_json({"error": str(exc), "exit_code": 1})
    except WebSocketDisconnect:
        return
