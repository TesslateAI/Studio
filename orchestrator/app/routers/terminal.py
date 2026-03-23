"""
Terminal v2 Router — dedicated terminal WebSocket with JWT auth.

Provides:
- GET  /{project_slug}/targets  — list running containers + static actions
- WS   /{project_slug}/connect  — authenticated terminal session
"""

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from ..config import get_settings
from ..database import AsyncSessionLocal, get_db
from ..models import Container, Project, ShellSession, User
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()

settings = get_settings()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _k8s_core_v1():
    """Lazy K8s CoreV1Api (uses broker's already-loaded config)."""
    return k8s_client.CoreV1Api()


@asynccontextmanager
async def _ws_db():
    """Yield an AsyncSession for WebSocket handlers (can't use Depends)."""
    async with AsyncSessionLocal() as session:
        yield session


async def _get_project(db: AsyncSession, project_slug: str, user_id: UUID) -> Project:
    """Resolve project by slug/UUID, verify access via RBAC."""
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, project_slug, user_id, Permission.TERMINAL_ACCESS
    )
    return project


async def _validate_ws_auth(token: str | None, websocket: WebSocket) -> UUID:
    """Authenticate via query-param JWT or cookie JWT. Return user_id."""
    # Try query param token first
    jwt_token = token if token else None

    # Fall back to cookie if no query param token
    if not jwt_token:
        jwt_token = websocket.cookies.get("tesslate_auth")

    if not jwt_token:
        raise ValueError("No authentication token provided")

    try:
        payload = jwt.decode(
            jwt_token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_aud": False},
        )
        sub = payload.get("sub")
        if sub is None:
            raise ValueError("missing sub")
        return UUID(sub)
    except (JWTError, ValueError) as e:
        raise ValueError(f"Invalid token: {e}") from e


async def _list_project_pods(namespace: str) -> list[dict]:
    """Query running pods in a project namespace, return target dicts."""
    v1 = _k8s_core_v1()
    targets: list[dict] = []
    try:
        pod_list = await asyncio.to_thread(
            v1.list_namespaced_pod,
            namespace=namespace,
            label_selector="tesslate.io/component in (dev-container,service-container)",
        )
    except ApiException as e:
        if e.status == 404:
            return []
        raise
    for pod in pod_list.items or []:
        if (pod.status.phase or "").lower() != "running":
            continue
        labels = pod.metadata.labels or {}
        container_id = labels.get("tesslate.io/container-id", "")
        if not container_id:
            continue
        port = None
        for ctr in pod.spec.containers or []:
            if ctr.ports:
                port = ctr.ports[0].container_port
                break
        targets.append(
            {
                "id": f"ctr:{container_id}",
                "name": labels.get("tesslate.io/container-directory", pod.metadata.name),
                "type": labels.get("tesslate.io/component", "dev-container"),
                "status": "running",
                "port": port,
                "container_directory": labels.get("tesslate.io/container-directory", ""),
            }
        )
    return targets


async def _resolve_pod_by_container_id(namespace: str, container_id: str) -> str:
    """Find running pod name by tesslate.io/container-id label."""
    v1 = _k8s_core_v1()
    pod_list = await asyncio.to_thread(
        v1.list_namespaced_pod,
        namespace=namespace,
        label_selector=f"tesslate.io/container-id={container_id}",
    )
    for pod in pod_list.items or []:
        if (pod.status.phase or "").lower() == "running":
            return pod.metadata.name
    raise RuntimeError(f"No running pod found for container-id={container_id}")


# ---------------------------------------------------------------------------
# GET /targets
# ---------------------------------------------------------------------------


@router.get("/{project_slug}/targets")
async def get_terminal_targets(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return available terminal targets for a project."""
    project = await _get_project(db, project_slug, current_user.id)
    namespace = f"proj-{project.id}"

    targets = await _list_project_pods(namespace)

    actions = [
        {"id": "ephemeral", "name": "Ephemeral Shell", "description": "lightweight pod, ~2s"},
    ]
    if project.compute_tier != "environment":
        actions.append(
            {
                "id": "environment",
                "name": "Start Environment",
                "description": "full dev server, ~10s",
            }
        )

    return {"targets": targets, "actions": actions}


# ---------------------------------------------------------------------------
# WS /connect — main terminal WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/{project_slug}/connect")
async def terminal_connect(
    websocket: WebSocket,
    project_slug: str,
    token: str = Query(""),
    target: str = Query(...),
):
    """Authenticated WebSocket terminal with provisioning support."""
    try:
        user_id = await _validate_ws_auth(token, websocket)
    except ValueError:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "Authentication failed"})
        await websocket.close(code=4401, reason="auth_failed")
        return

    await websocket.accept()

    # Short-lived session for project lookup and environment start
    async with _ws_db() as db:
        try:
            project = await _get_project(db, project_slug, user_id)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "message": exc.detail})
            await websocket.close()
            return

        namespace = f"proj-{project.id}"
        ephemeral_pod_name: str | None = None
        ephemeral_ns: str | None = None
        shell_session_id: UUID | None = None

        try:
            if target.startswith("ctr:"):
                pod_name = await _handle_container_target(websocket, namespace, target)
            elif target == "ephemeral":
                pod_name, ephemeral_ns = await _handle_ephemeral_target(websocket, project)
                ephemeral_pod_name = pod_name
            elif target == "environment":
                pod_name = await _handle_environment_target(
                    websocket, namespace, project, user_id, db
                )
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown target: {target}"})
                await websocket.close()
                return
        except WebSocketDisconnect:
            logger.info(f"[TERM] WS disconnected during provisioning for {project_slug}")
            return
        except Exception as e:
            logger.error(f"[TERM] Provisioning error for {project_slug}: {e}", exc_info=True)
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "error", "message": str(e)})
            with contextlib.suppress(Exception):
                await websocket.close()
            return

    # Audit trail — record non-ephemeral sessions (own session, released immediately)
    if not target.startswith("ephemeral"):
        try:
            async with _ws_db() as audit_db:
                # Enforce session limits (same as ShellSessionManager)
                count_result = await audit_db.execute(
                    select(func.count())
                    .select_from(ShellSession)
                    .where(ShellSession.project_id == project.id, ShellSession.status == "active")
                )
                active_count = count_result.scalar() or 0
                if active_count < 100:
                    shell_session = ShellSession(
                        session_id=str(uuid4()),
                        user_id=user_id,
                        project_id=project.id,
                        container_name=pod_name,
                        status="active",
                    )
                    audit_db.add(shell_session)
                    await audit_db.commit()
                    shell_session_id = shell_session.id
                else:
                    logger.warning(f"[TERM] Session limit (100) reached for project {project.id}")
        except Exception:
            logger.warning(
                f"[TERM] Failed to create ShellSession audit record for {project_slug}",
                exc_info=True,
            )

    # PTY session — long-lived, no DB session held open
    try:
        session_ns = ephemeral_ns if ephemeral_pod_name else namespace
        pty_container = "cmd" if ephemeral_pod_name else "dev-server"
        await _run_pty_session(
            websocket,
            project,
            session_ns,
            pod_name,
            container=pty_container,
            shell_session_id=shell_session_id,
        )
    except WebSocketDisconnect:
        logger.info(f"[TERM] WS disconnected for {project_slug}")
    except Exception as e:
        logger.error(f"[TERM] Error for {project_slug}: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        # Clean up ephemeral pod (isolated so failures don't skip audit update)
        if ephemeral_pod_name and ephemeral_ns:
            with contextlib.suppress(Exception):
                from ..services.compute_manager import get_compute_manager

                await get_compute_manager().delete_pod(ephemeral_pod_name, ephemeral_ns)

        # Mark shell session closed
        if shell_session_id:
            try:
                async with _ws_db() as close_db:
                    await close_db.execute(
                        sql_update(ShellSession)
                        .where(ShellSession.id == shell_session_id)
                        .values(status="closed", closed_at=func.now())
                    )
                    await close_db.commit()
            except Exception:
                logger.warning(
                    f"[TERM] Failed to close ShellSession {shell_session_id}", exc_info=True
                )


# ---------------------------------------------------------------------------
# Target handlers
# ---------------------------------------------------------------------------


async def _handle_container_target(
    websocket: WebSocket,
    namespace: str,
    target: str,
) -> str:
    """Resolve ctr:<uuid> to a pod name."""
    container_id = target.removeprefix("ctr:")
    pod_name = await _resolve_pod_by_container_id(namespace, container_id)
    await websocket.send_json({"type": "ready"})
    return pod_name


async def _handle_ephemeral_target(
    websocket: WebSocket,
    project: Project,
) -> tuple[str, str]:
    """Create an ephemeral pod via ComputeManager. Returns (pod_name, namespace)."""
    from ..services.compute_manager import get_compute_manager

    if not project.volume_id or not project.cache_node:
        raise RuntimeError("Project has no volume — start the environment first")

    await websocket.send_json({"type": "provisioning", "message": "Creating ephemeral pod..."})

    cm = get_compute_manager()
    pod_name, ns = await cm.create_ephemeral_pod(
        volume_id=project.volume_id,
        node_name=project.cache_node,
        project_id=str(project.id),
    )

    await websocket.send_json({"type": "provisioning", "message": "Waiting for pod to start..."})
    await cm.wait_for_pod_running(pod_name, ns)
    await websocket.send_json({"type": "ready"})
    return pod_name, ns


async def _handle_environment_target(
    websocket: WebSocket,
    namespace: str,
    project: Project,
    user_id: UUID,
    db: AsyncSession,
) -> str:
    """Start environment via ComputeManager, then wait for container selection."""
    from ..services.compute_manager import get_compute_manager

    await websocket.send_json({"type": "provisioning", "message": "Starting environment..."})

    result = await db.execute(select(Container).where(Container.project_id == project.id))
    containers = list(result.scalars().all())

    progress_queue: asyncio.Queue = asyncio.Queue()
    cm = get_compute_manager()

    async def run_start():
        return await cm.start_environment(
            project=project,
            containers=containers,
            connections=[],
            user_id=user_id,
            db=db,
            progress_queue=progress_queue,
        )

    start_task = asyncio.create_task(run_start())

    # Forward progress to WS
    try:
        while not start_task.done():
            try:
                msg = await asyncio.wait_for(progress_queue.get(), timeout=5.0)
                await websocket.send_json(
                    {"type": "provisioning", "message": msg.get("message", "...")}
                )
            except TimeoutError:
                await websocket.send_json(
                    {"type": "provisioning", "message": "Still provisioning..."}
                )
    except Exception:
        if not start_task.done():
            start_task.cancel()
        raise

    # Drain any remaining progress messages
    while not progress_queue.empty():
        msg = progress_queue.get_nowait()
        await websocket.send_json({"type": "provisioning", "message": msg.get("message", "...")})

    # Propagate errors
    await start_task

    # Poll for running containers (pods may still be transitioning from Pending)
    targets: list[dict] = []
    for _attempt in range(15):  # 30s max (15 × 2s)
        targets = await _list_project_pods(namespace)
        if targets:
            break
        await asyncio.sleep(2)
        await websocket.send_json({"type": "provisioning", "message": "Waiting for containers..."})
    if not targets:
        raise RuntimeError("Environment started but no running containers found after 30s")

    if len(targets) == 1:
        container_id = targets[0]["id"].removeprefix("ctr:")
        pod_name = await _resolve_pod_by_container_id(namespace, container_id)
        await websocket.send_json({"type": "ready"})
        return pod_name

    # Multiple containers — ask client to pick
    await websocket.send_json({"type": "select_container", "targets": targets})

    while True:
        raw = await websocket.receive_text()
        data = json.loads(raw)
        if data.get("type") == "select" and data.get("target_id", "").startswith("ctr:"):
            container_id = data["target_id"].removeprefix("ctr:")
            pod_name = await _resolve_pod_by_container_id(namespace, container_id)
            await websocket.send_json({"type": "ready"})
            return pod_name


# ---------------------------------------------------------------------------
# PTY session loop
# ---------------------------------------------------------------------------


async def _run_pty_session(
    websocket: WebSocket,
    project: Project,
    namespace: str,
    pod_name: str,
    container: str = "dev-server",
    shell_session_id: UUID | None = None,
):
    """Attach PTY broker and run bidirectional I/O until disconnect."""
    from ..services.pty_broker import get_pty_broker

    broker = get_pty_broker()
    session = await broker.create_session(
        user_id=project.owner_id,
        project_id=str(project.id),
        command="cd /app && exec /bin/sh",
        namespace=namespace,
        pod_name=pod_name,
        container=container,
    )

    # Link PTY broker session_id to the audit record
    if shell_session_id:
        try:
            async with _ws_db() as link_db:
                await link_db.execute(
                    sql_update(ShellSession)
                    .where(ShellSession.id == shell_session_id)
                    .values(session_id=session.session_id)
                )
                await link_db.commit()
        except Exception:
            logger.warning(
                f"[TERM] Failed to link PTY session_id to ShellSession {shell_session_id}"
            )

    output_task = None
    try:

        async def stream_output():
            try:
                while True:
                    new_data, is_eof = await session.read_new_output()
                    if new_data:
                        await websocket.send_json(
                            {
                                "type": "output",
                                "data": new_data.decode("utf-8", errors="replace"),
                            }
                        )
                    if is_eof:
                        break
                    await asyncio.sleep(0.05)
            except (WebSocketDisconnect, Exception):
                pass

        output_task = asyncio.create_task(stream_output())

        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") == "input":
                input_bytes = data.get("data", "").encode("utf-8")
                await broker.write_to_pty(session.session_id, input_bytes)
            elif data.get("type") == "resize":
                cols = data.get("cols", 80)
                rows = data.get("rows", 24)
                await broker.resize(session.session_id, cols, rows)

    finally:
        if output_task:
            output_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await output_task
        await broker.close_session(session.session_id)
