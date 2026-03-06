# Shell Session Manager - PTY-Based Terminal Access

**File**: `orchestrator/app/services/shell_session_manager.py` (632 lines)

Manages PTY-based shell sessions for user terminal access to running containers. Provides secure, audited shell access with resource limits and session tracking.

## Overview

The Shell Session Manager coordinates between:
- **PTY Broker** (`pty_broker.py`) - Low-level PTY process management
- **Database** (ShellSession model) - Session metadata and audit trail
- **Orchestrator** - Container/pod name resolution and readiness checks

## Architecture

```
Shell Session Flow
┌────────────────────────────────────────────────────────────┐
│ 1. Client Request                                           │
│    POST /api/shell/create {project_id, container_name}     │
└────────────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────────────┐
│ 2. ShellSessionManager.create_session()                    │
│    ├─ Validate user owns project                            │
│    ├─ Check session limits (100 per user/project)           │
│    ├─ Resolve container name (Docker or K8s)               │
│    ├─ Verify container is running                           │
│    └─ Create PTY session via pty_broker                    │
└────────────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────────────┐
│ 3. PTYBroker.create_session()                              │
│    ├─ Spawn PTY process (docker exec or kubectl exec)      │
│    ├─ Track in memory: self.sessions[session_id]           │
│    └─ Return PTYSession object                              │
└────────────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────────────┐
│ 4. Save to Database                                        │
│    ShellSession(session_id, user_id, project_id, ...)     │
└────────────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────────────┐
│ 5. WebSocket Communication                                 │
│    ├─ Client sends: write_to_session(session_id, "ls\n")  │
│    ├─ Client polls: read_output(session_id)                │
│    └─ PTY → stdout → base64 → WebSocket → Client          │
└────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. Resource Limits

```python
class ShellSessionManager:
    MAX_SESSIONS_PER_USER = 100
    MAX_SESSIONS_PER_PROJECT = 100
    IDLE_TIMEOUT_MINUTES = 30
    MAX_SESSION_DURATION_HOURS = 8
    MAX_OUTPUT_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB
```

### 2. Session Creation

```python
async def create_session(
    self,
    user_id: UUID,
    project_id: str,
    db: AsyncSession,
    command: str = "/bin/sh",
    container_name: Optional[str] = None
) -> Dict[str, Any]:
    """Create shell session with validation and limits."""

    # 1. Validate user owns project
    project = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == user_id
        )
    )

    # 2. Check limits
    user_sessions = await self._get_user_active_sessions(user_id, db)
    if len(user_sessions) >= self.MAX_SESSIONS_PER_USER:
        raise HTTPException(status_code=429, detail="Too many sessions")

    # 3. Resolve container name (Docker: my-app-frontend, K8s: dev-frontend)
    resolved_name = await self._get_container_name(
        user_id, project_id, project.slug, container_name
    )

    # 4. Verify container is running
    is_running = await self._is_container_running(
        user_id, project_id, project.slug, container_name
    )
    if not is_running:
        raise HTTPException(status_code=400, detail="Container not running")

    # 5. Create PTY session
    pty_session = await self.pty_broker.create_session(
        user_id=user_id,
        project_id=project_id,
        container_name=resolved_name,
        command=command
    )

    # 6. Save to database
    db_session = ShellSession(
        session_id=pty_session.session_id,
        user_id=user_id,
        project_id=project_id,
        container_name=resolved_name,
        command=command,
        status="active"
    )
    db.add(db_session)
    await db.commit()

    # 7. Track in memory
    self.active_sessions[pty_session.session_id] = pty_session

    return {"session_id": pty_session.session_id, "status": "active"}
```

### 3. Container Name Resolution

Handles Docker vs Kubernetes naming differences:

```python
async def _get_container_name(
    self,
    user_id: UUID,
    project_id: str,
    project_slug: str,
    container_name: Optional[str]
) -> str:
    """Resolve container/pod name for deployment mode."""

    if is_kubernetes_mode():
        # K8s: dev-{container-directory}
        if container_name:
            safe_name = container_name.lower().replace('_', '-')
            return f"dev-{safe_name}"
        else:
            # Find first running dev container
            pods = await k8s_client.list_namespaced_pod(
                namespace=f"proj-{project_id}",
                label_selector="tesslate.io/component=dev-container"
            )
            return pods.items[0].metadata.labels.get('app', 'dev')

    else:  # Docker mode
        # Docker: {project-slug}-{service-name}
        if container_name:
            sanitized = container_name.lower().replace(' ', '-')
            return f"{project_slug}-{sanitized}"
        else:
            # Get first running container from docker-compose
            status = await orchestrator.get_project_status(project_slug, project_id)
            for service_name, info in status['containers'].items():
                if info.get('running'):
                    return info.get('name')
```

### 4. Write to Session

```python
async def write_to_session(
    self,
    session_id: str,
    data: bytes,
    db: AsyncSession,
    user_id: Optional[UUID] = None
) -> None:
    """Write data to PTY stdin."""

    session = self.active_sessions.get(session_id)
    if not session:
        # Try to recover from pty_broker
        session = self.pty_broker.sessions.get(session_id)
        if not session:
            raise ValueError("Session not found")

    # Authorization check
    if user_id and session.user_id != user_id:
        raise PermissionError("Session belongs to different user")

    # Write to PTY
    await self.pty_broker.write_to_pty(session_id, data)

    # Queue stats update (batched, non-blocking)
    self.pending_stats_updates.add(session_id)
```

### 5. Read Output

```python
async def read_output(
    self,
    session_id: str,
    db: AsyncSession,
    user_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """Read new output since last read."""

    session = self.active_sessions.get(session_id)
    if not session:
        raise ValueError("Session not found")

    # Authorization check
    if user_id and session.user_id != user_id:
        raise PermissionError("Session belongs to different user")

    # Get new output from PTY
    new_data, is_eof = await session.read_new_output()

    # Queue stats update
    self.pending_stats_updates.add(session_id)

    return {
        "output": base64.b64encode(new_data).decode('utf-8'),
        "bytes": len(new_data),
        "is_eof": is_eof
    }
```

### 6. Cleanup

```python
async def cleanup_idle_sessions(self, db: AsyncSession) -> int:
    """Clean up idle sessions (background task)."""

    cutoff_time = datetime.utcnow() - timedelta(minutes=self.IDLE_TIMEOUT_MINUTES)

    idle_sessions = await db.execute(
        select(ShellSession).where(
            ShellSession.status == "active",
            ShellSession.last_activity_at < cutoff_time
        )
    )

    closed_count = 0
    for session in idle_sessions.scalars():
        await self.close_session(session.session_id, db)
        closed_count += 1

    return closed_count
```

## PTY Broker Details

**File**: `orchestrator/app/services/pty_broker.py` (700 lines)

Low-level PTY process management:

```python
class PTYBroker:
    """Manages PTY processes for shell sessions."""

    def __init__(self):
        self.sessions: Dict[str, PTYSession] = {}

    async def create_session(
        self,
        user_id: UUID,
        project_id: str,
        container_name: str,
        command: str = "/bin/sh"
    ) -> PTYSession:
        """Spawn PTY process."""

        session_id = str(uuid.uuid4())

        if is_kubernetes_mode():
            # Kubernetes: kubectl exec with PTY
            cmd = [
                'kubectl', 'exec', '-it',
                '-n', f'proj-{project_id}',
                f'deployment/dev-{container_name}',
                '--', command
            ]
        else:
            # Docker: docker exec with PTY
            cmd = ['docker', 'exec', '-it', container_name, command]

        # Spawn PTY process
        master_fd, slave_fd = pty.openpty()
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd
        )

        session = PTYSession(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            master_fd=master_fd,
            process=process
        )

        self.sessions[session_id] = session
        return session

    async def write_to_pty(self, session_id: str, data: bytes):
        """Write to PTY stdin."""
        session = self.sessions[session_id]
        os.write(session.master_fd, data)

    async def close_session(self, session_id: str):
        """Close PTY and terminate process."""
        session = self.sessions.pop(session_id)
        os.close(session.master_fd)
        session.process.terminate()
        await session.process.wait()
```

## Usage Example

### From Router (WebSocket)

```python
# routers/shell.py
from services.shell_session_manager import get_shell_session_manager

@router.websocket("/ws/shell/{session_id}")
async def shell_websocket(
    websocket: WebSocket,
    session_id: str,
    current_user: User
):
    await websocket.accept()
    manager = get_shell_session_manager()

    try:
        while True:
            # Receive from client
            data = await websocket.receive_bytes()

            # Write to PTY
            await manager.write_to_session(
                session_id=session_id,
                data=data,
                db=db,
                user_id=current_user.id
            )

            # Read output
            output = await manager.read_output(
                session_id=session_id,
                db=db,
                user_id=current_user.id
            )

            # Send to client
            await websocket.send_json(output)

    except WebSocketDisconnect:
        await manager.close_session(session_id, db)
```

### Create Session

```python
from services.shell_session_manager import get_shell_session_manager

manager = get_shell_session_manager()

session = await manager.create_session(
    user_id=user.id,
    project_id=project.id,
    db=db,
    command="/bin/bash",  # Or /bin/sh
    container_name="Frontend"  # Optional
)

print(f"Session created: {session['session_id']}")
```

## Security Features

1. **Authorization**: Every operation checks user owns session
2. **Resource Limits**: Max sessions per user/project
3. **Timeouts**: Auto-close idle sessions after 30 minutes
4. **Command Validation**: Optional command whitelist (command_validator.py)
5. **Audit Trail**: All sessions logged to database
6. **Container Isolation**: Can't access other users' containers

## Performance Optimizations

1. **Batched Stats Updates**: Don't update DB on every keystroke
2. **In-Memory Tracking**: Fast session lookup without DB queries
3. **Lazy Cleanup**: Background task removes idle sessions
4. **Output Buffering**: Read in chunks, not byte-by-byte

## Troubleshooting

**Problem**: Session creation fails with "Container not running"
- Check container status: `orchestrator.get_container_status()`
- Verify container name resolution
- For K8s: Check pod is ready

**Problem**: PTY output garbled
- Check terminal size settings
- Verify WebSocket binary mode
- Ensure proper encoding (base64)

**Problem**: Session stuck/frozen
- Check PTY process is alive
- Look for blocking I/O in container
- Verify network connectivity

## Related Documentation

- [pty_broker.md](./pty_broker.md) - PTY process management details
- [orchestration.md](./orchestration.md) - Container name resolution
- [../routers/shell.md](../routers/shell.md) - Shell API endpoints
