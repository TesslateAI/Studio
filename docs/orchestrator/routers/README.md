# Orchestrator Routers

API routers for OpenSail's FastAPI backend. Each router handles a specific domain of functionality.

## Router Organization

Routers are organized by feature domain, not by database model. This allows for clear separation of concerns and makes it easy to find the right endpoint for a given task.

```
orchestrator/app/routers/
├── projects.py              # Project CRUD, files, containers, assets
├── chat.py                  # Chat management, agent streaming
├── marketplace.py           # Agent/base marketplace, purchases, reviews
├── billing.py               # Subscriptions, credits, usage tracking
├── git.py                   # Git operations (init, commit, push, pull)
├── git_providers.py         # Multi-provider Git support
├── deployments.py           # External deployments (Vercel, Netlify, Cloudflare)
├── deployment_credentials.py # OAuth credentials for deployments
├── deployment_oauth.py      # OAuth callback handling
├── admin.py                 # Platform metrics, user management
├── auth.py                  # Custom auth endpoints (pod access verification)
├── users.py                 # User profile management
├── agents.py                # Agent management (user agents)
├── agent.py                 # Legacy agent endpoints
├── shell.py                 # Interactive shell sessions
├── secrets.py               # Project environment variables
├── kanban.py                # Project task board
├── tasks.py                 # Background task status
├── feedback.py              # User feedback submission
├── referrals.py             # Referral program
├── creators.py              # Creator program management
├── github.py                # GitHub-specific operations
├── webhooks.py              # Webhook endpoints
├── channels.py              # Messaging channels (Telegram, Slack, Discord, WhatsApp)
├── mcp.py                   # MCP server install/manage, agent assignments
└── mcp_server.py            # Tesslate-as-MCP-server (Streamable HTTP)
```

## Base Paths

Most routers define their base path using `prefix` in the APIRouter:

```python
router = APIRouter(prefix="/api/projects", tags=["projects"])
```

Key base paths:
- `/api/projects` - Project management, setup config, project analysis
- `/api/chat` - Chat and agent interactions
- `/api/marketplace` - Agent, skill, base, and MCP server marketplace
- `/api/billing` - Subscription and billing
- `/api/deployments` - External deployments
- `/api/admin` - Admin operations (superuser only)
- `/api/auth` - Authentication
- `/api/git` - Git operations (typically nested under projects)
- `/api/channels` - Messaging channel integrations
- `/api/mcp` - MCP server management and agent assignments
- `/api/mcp/server` - Tesslate-as-MCP-server (Streamable HTTP)

Some routers don't define a prefix and expect the including router to handle it. For example, `auth.py` is mounted at `/api/auth` by `main.py`.

## Common Patterns

### Authentication

All routers use FastAPI dependency injection for authentication:

```python
from ..users import current_active_user, current_superuser

@router.get("/endpoint")
async def my_endpoint(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # User is authenticated and available as current_user
    pass
```

**current_active_user**: Requires valid JWT token (cookie or bearer)
**current_superuser**: Requires superuser role (for admin endpoints)

### Database Session

All endpoints that need database access use the `get_db` dependency:

```python
@router.get("/endpoint")
async def my_endpoint(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).where(...))
    return result.scalars().all()
```

The session is automatically committed/rolled back based on success/failure.

### Error Handling

Endpoints use HTTPException for error responses:

```python
if not resource:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found"
    )
```

Common status codes:
- `400 BAD_REQUEST` - Invalid input, validation errors
- `401 UNAUTHORIZED` - Authentication required
- `403 FORBIDDEN` - User doesn't have permission
- `404 NOT_FOUND` - Resource not found
- `500 INTERNAL_SERVER_ERROR` - Unexpected server error

### Background Tasks

Long-running operations use FastAPI's BackgroundTasks:

```python
@router.post("/start")
async def start_operation(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Queue background task
    background_tasks.add_task(perform_operation, arg1, arg2)
    return {"message": "Operation started"}
```

For longer tasks that need progress tracking, use the TaskManager service (see `orchestrator/app/services/task_manager.py`).

### Streaming Responses

Agents and build operations use Server-Sent Events (SSE) for streaming:

```python
from fastapi.responses import StreamingResponse

@router.post("/stream")
async def stream_endpoint():
    async def generate():
        yield f"data: {json.dumps(event_data)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )
```

The frontend listens for these events using EventSource or fetch with streaming.

### WebSocket Connections

Chat uses WebSocket for real-time bidirectional communication:

```python
@router.websocket("/ws/{chat_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: str
):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Process and send response
            await websocket.send_text(response)
    except WebSocketDisconnect:
        pass
```

### Pagination

List endpoints support pagination via query parameters:

```python
@router.get("/items")
async def list_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100)
):
    # Apply offset and limit to query
    pass
```

### File Uploads

File upload endpoints use FastAPI's `UploadFile`:

```python
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...)
):
    contents = await file.read()
    # Process file
    return {"filename": file.filename}
```

## Adding a New Router

1. **Create the router file** in `orchestrator/app/routers/`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..users import current_active_user
from ..models import YourModel

router = APIRouter(prefix="/api/your-feature", tags=["your-feature"])

@router.get("/")
async def list_items(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Implementation
    pass
```

2. **Import and include in main.py**:

```python
from .routers import your_feature

app.include_router(your_feature.router)
```

3. **Create schemas** in `orchestrator/app/schemas.py` (or `schemas_*.py`):

```python
from pydantic import BaseModel

class YourFeatureCreate(BaseModel):
    name: str

class YourFeatureResponse(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True
```

4. **Add database models** if needed in `orchestrator/app/models.py`

5. **Write tests** in `orchestrator/tests/test_your_feature.py`

6. **Document the router** in `docs/orchestrator/routers/your_feature.md`

## Testing Endpoints

Use pytest with async support:

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_endpoint(client: AsyncClient, authenticated_user):
    response = await client.get("/api/endpoint")
    assert response.status_code == 200
```

Or use FastAPI's TestClient for sync tests:

```python
from fastapi.testclient import TestClient

def test_endpoint(client: TestClient):
    response = client.get("/api/endpoint")
    assert response.status_code == 200
```

## Security Considerations

1. **Always validate user ownership** before allowing access to resources
2. **Never trust client input** - use Pydantic schemas for validation
3. **Use parameterized queries** - SQLAlchemy handles this automatically
4. **Log security-relevant events** (failed auth, unauthorized access attempts)
5. **Rate limit sensitive endpoints** (login, password reset, file uploads)
6. **Sanitize file paths** - use `os.path.abspath()` and validate against project directory
7. **Encrypt sensitive data** - use encryption service for tokens, credentials

## Performance Optimization

1. **Use async operations** for all I/O (database, filesystem, HTTP)
2. **Eager load relationships** with `selectinload()` to avoid N+1 queries
3. **Index frequently queried fields** in database models
4. **Cache expensive operations** (model lists, marketplace data)
5. **Stream large responses** instead of loading into memory
6. **Use background tasks** for long-running operations
7. **Paginate list endpoints** to limit result set size

## Related Documentation

- [API Schemas](../schemas.md) - Request/response models
- [Database Models](../models.md) - Database schema
- [Services](../services/) - Business logic services
- [Agent System](../agent/) - AI agent implementation
- [Deployment Modes](../../k8s/ARCHITECTURE.md) - Docker vs Kubernetes

## Router Documentation Index

- [projects.md](projects.md) - Project CRUD, files, containers, setup config, project analysis
- [marketplace.md](marketplace.md) - Agent, skill, base, and MCP server marketplace
- [chat.md](chat.md) - Chat management, agent streaming
- [channels.md](channels.md) - Messaging channel integrations (Telegram, Slack, Discord, WhatsApp)
- [mcp.md](mcp.md) - MCP server install/manage, agent assignments, Tesslate MCP server
- [deployments.md](deployments.md) - External deployments (Vercel, Netlify, Cloudflare)
- [billing.md](billing.md) - Subscriptions, credits, usage tracking
- [admin.md](admin.md) - Platform metrics, user management
- [git.md](git.md) - Git operations
- [themes.md](themes.md) - Theme API (public endpoints)
- [external-agent.md](external-agent.md) - External agent API (API keys, SSE, webhooks)
