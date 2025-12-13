"""
Task Status API
Endpoints for tracking background operation status and real-time updates.
"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from typing import List, Optional
import asyncio
import json

from ..models import User
from ..users import current_active_user
from ..services.task_manager import get_task_manager, Task, TaskStatus

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(current_active_user)
):
    """Get status of a specific task"""
    task_manager = get_task_manager()
    task = task_manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify user owns this task
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return task.to_dict()


@router.get("/user/active")
async def get_active_tasks(
    current_user: User = Depends(current_active_user)
):
    """Get all active tasks for the current user"""
    task_manager = get_task_manager()
    tasks = task_manager.get_user_tasks(current_user.id, active_only=True)
    return [task.to_dict() for task in tasks]


@router.get("/user/all")
async def get_all_tasks(
    limit: int = 50,
    current_user: User = Depends(current_active_user)
):
    """Get all tasks for the current user (most recent first)"""
    task_manager = get_task_manager()
    tasks = task_manager.get_user_tasks(current_user.id, active_only=False)
    return [task.to_dict() for task in tasks[:limit]]


@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(current_active_user)
):
    """Cancel a running task"""
    task_manager = get_task_manager()
    task = task_manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="Task cannot be cancelled")

    # Cancel the background task
    background_task = task_manager._background_tasks.get(task_id)
    if background_task:
        background_task.cancel()

    await task_manager.update_task_status(task_id, TaskStatus.CANCELLED)

    return {"message": "Task cancelled", "task_id": task_id}


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_task_update(self, user_id: int, task: Task):
        """Send task update to all user's connections"""
        if user_id not in self.active_connections:
            return

        message = json.dumps({
            "type": "task_update",
            "task": task.to_dict()
        })

        # Send to all connections for this user
        dead_connections = []
        for connection in self.active_connections[user_id]:
            try:
                await connection.send_text(message)
            except Exception:
                dead_connections.append(connection)

        # Clean up dead connections
        for dead in dead_connections:
            self.disconnect(dead, user_id)

    async def send_notification(self, user_id: int, notification: dict):
        """Send a notification to user"""
        if user_id not in self.active_connections:
            return

        message = json.dumps({
            "type": "notification",
            "notification": notification
        })

        for connection in self.active_connections[user_id]:
            try:
                await connection.send_text(message)
            except Exception:
                pass


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time task updates

    Client should send authentication token in first message:
    {"token": "bearer_token"}

    Server sends updates in format:
    {"type": "task_update", "task": {...}}
    {"type": "notification", "notification": {...}}
    """
    await websocket.accept()

    try:
        # Wait for authentication
        auth_data = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        auth_json = json.loads(auth_data)
        token = auth_json.get("token", "").replace("Bearer ", "")

        # Authenticate user
        from ..auth import verify_token_for_user
        from ..database import get_db

        # Get database session
        db_gen = get_db()
        db = await db_gen.__anext__()

        try:
            user = await verify_token_for_user(token, db)
        finally:
            await db_gen.aclose()

        if not user:
            await websocket.close(code=1008, reason="Authentication failed")
            return

        # Register connection
        await manager.connect(websocket, user.id)

        # Subscribe to task updates
        task_manager = get_task_manager()

        async def task_callback(task: Task):
            """Called when a task is updated"""
            if task.user_id == user.id:
                await manager.send_task_update(user.id, task)

        # Send current active tasks
        active_tasks = task_manager.get_user_tasks(user.id, active_only=True)
        for task in active_tasks:
            await manager.send_task_update(user.id, task)
            # Subscribe to updates for each active task
            task_manager.subscribe(task.id, task_callback)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                data = await websocket.receive_text()
                # Handle ping/pong or other client messages
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"WebSocket error: {e}")
                break

    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="Authentication timeout")
    except Exception as e:
        print(f"WebSocket connection error: {e}")
    finally:
        if 'user' in locals() and user is not None:
            manager.disconnect(websocket, user.id)


# Helper function to send notifications through WebSocket
async def send_notification_to_user(user_id: int, title: str, message: str, type: str = "info"):
    """
    Send a notification to a user via WebSocket

    Args:
        user_id: User ID
        title: Notification title
        message: Notification message
        type: Notification type (info, success, warning, error)
    """
    notification = {
        "title": title,
        "message": message,
        "type": type,
        "timestamp": asyncio.get_event_loop().time()
    }
    await manager.send_notification(user_id, notification)


# Expose manager for use in other modules
def get_connection_manager() -> ConnectionManager:
    return manager
