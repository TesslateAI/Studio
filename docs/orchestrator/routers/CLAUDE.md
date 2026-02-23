# Orchestrator Routers Context - Agent Instructions

**Purpose**: API endpoint development for Tesslate Studio's FastAPI backend

**When to load this context**: When adding or modifying API endpoints, routers, or HTTP handlers

## Key Files

### Router Files
Located in `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/`:

- `projects.py` (5218 lines) - Project CRUD, file operations, container lifecycle, assets, deployment target assignment
- `chat.py` (~2050 lines) - Chat management, agent streaming, WebSocket support (max_iterations default: unlimited, cost limit: $5/run)
- `marketplace.py` (~2800 lines) - Agent/base marketplace, purchases, reviews, user-submitted bases, community bases browse with pagination, base versioning (git tags)
- `admin.py` (~3700 lines) - Platform metrics, user management, moderation, audit logs, project admin, billing admin, deployment monitoring
- `deployments.py` (1,197 lines) - External deployments (Vercel, Netlify, Cloudflare), deploy-all endpoint
- `kanban.py` (757 lines) - Project task board management
- `billing.py` (702 lines) - Subscriptions, credits, usage tracking, Stripe webhooks
- `git.py` (607 lines) - Git operations (init, commit, push, pull)
- `git_providers.py` (533 lines) - Multi-provider Git support (GitHub, GitLab, Bitbucket)
- `deployment_credentials.py` (519 lines) - OAuth credential management
- `github.py` (474 lines) - GitHub-specific operations (legacy, use git_providers instead)
- `deployment_oauth.py` (447 lines) - OAuth callback handling
- `feedback.py` (401 lines) - User feedback submission
- `agent.py` (374 lines) - Legacy agent endpoints
- `secrets.py` (293 lines) - Project environment variables
- `tasks.py` (258 lines) - Background task status queries
- `shell.py` (246 lines) - Interactive shell sessions
- `creators.py` (238 lines) - Creator program management
- `two_fa.py` (218 lines) - Email 2FA login, code verification, resend, password reset
- `auth.py` (222 lines) - Pod access verification, custom auth
- `users.py` (128 lines) - User profile management
- `agents.py` (108 lines) - User agent management
- `themes.py` - Public theme API (no auth required)
- `webhooks.py` (52 lines) - Webhook endpoints
- `referrals.py` (46 lines) - Referral program

### Supporting Files
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/main.py` - FastAPI app setup, middleware, router registration
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/schemas.py` - Pydantic request/response models
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - SQLAlchemy database models
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/users.py` - FastAPI Users configuration

## Related Contexts

Load these contexts when working on related functionality:

- **Services**: `docs/orchestrator/services/CLAUDE.md` - Business logic, orchestration, external integrations
- **Models**: `docs/orchestrator/models.md` - Database schema and relationships
- **Agent**: `docs/orchestrator/agent/CLAUDE.md` - AI agent implementation, tools, streaming
- **Schemas**: `docs/orchestrator/schemas.md` - Pydantic models for validation

## Quick Reference

### Common Decorators

```python
# Public endpoints (no auth)
@router.get("/public")
async def public_endpoint():
    pass

# Authenticated endpoints
@router.get("/private")
async def private_endpoint(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    pass

# Admin-only endpoints
@router.get("/admin")
async def admin_endpoint(
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
):
    pass

# Background task support
@router.post("/async-operation")
async def async_operation(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_active_user)
):
    background_tasks.add_task(do_work, arg1, arg2)
    return {"status": "started"}

# Streaming responses
@router.get("/stream")
async def stream_data():
    async def generate():
        yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# WebSocket endpoints
@router.websocket("/ws/{id}")
async def websocket_endpoint(websocket: WebSocket, id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(response)
    except WebSocketDisconnect:
        pass
```

### Public and Optional Auth Patterns

Some endpoints are publicly accessible (no auth required) or support optional authentication:

```python
# Public endpoint (themes, marketplace browsing)
@router.get("/themes")
async def get_themes(db: AsyncSession = Depends(get_db)):
    # No current_user dependency - anyone can access
    return await get_all_themes(db)

# Optional auth - works for both authenticated and anonymous users
@router.get("/marketplace/agents")
async def get_agents(
    current_user: Optional[User] = Depends(current_optional_user),
    db: AsyncSession = Depends(get_db)
):
    # current_user is None for anonymous, User for authenticated
    agents = await get_public_agents(db)
    if current_user:
        # Add user-specific data (purchased, in library, etc.)
        agents = add_user_context(agents, current_user)
    return agents
```

**Public Routers:**
- `themes.py` - Theme presets (needed before login for UI)
- `marketplace.py` - Agent browsing (public access, optional auth for user context)

### New Marketplace Endpoints

**Browse Community Bases** (`GET /api/marketplace/bases/browse`):
- Server-side paginated with `page`, `limit`, `category`, `search`, `sort` params
- Returns `{ bases, total, page, total_pages }`
- Includes official + community bases with creator info
- Stable pagination sort with `.id` tiebreaker

**Base Versions** (`GET /api/marketplace/bases/{slug}/versions`):
- Returns available git tag versions for a base
- 10-minute server-side cache per slug
- Fetches tags from GitHub API (unauthenticated, 60 req/hr rate limit)
- Used by `CreateProjectModal` for version selection

**Project Creation with Version** (`POST /api/projects`):
- `ProjectCreate` schema now accepts optional `base_version` field
- Clones the specific git tag via `--branch` instead of latest when provided

### Authentication Patterns

```python
# Verify project ownership
from .projects import get_project_by_slug

project = await get_project_by_slug(db, project_slug, current_user.id)
# Raises HTTPException if not found or not owned

# Manual ownership check
result = await db.execute(
    select(Project).where(
        Project.id == project_id,
        Project.owner_id == current_user.id
    )
)
project = result.scalar_one_or_none()
if not project:
    raise HTTPException(status_code=404, detail="Project not found")

# Superuser check
if not current_user.is_superuser:
    raise HTTPException(status_code=403, detail="Admin access required")
```

### Database Patterns

```python
# Query with eager loading (avoid N+1)
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(Project)
    .options(selectinload(Project.containers))
    .where(Project.id == project_id)
)
project = result.scalar_one()

# Query with filters
result = await db.execute(
    select(MarketplaceAgent)
    .where(
        MarketplaceAgent.status == "published",
        MarketplaceAgent.category == category
    )
    .order_by(MarketplaceAgent.downloads.desc())
    .limit(20)
)
agents = result.scalars().all()

# Aggregations
from sqlalchemy import func

count = await db.scalar(
    select(func.count(Project.id))
    .where(Project.owner_id == user_id)
)

# Transactions (auto-commit on success)
project = Project(name="New Project", owner_id=user_id)
db.add(project)
await db.commit()
await db.refresh(project)  # Refresh to get generated ID
```

### Error Handling

```python
from fastapi import HTTPException, status

# Standard errors
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Resource not found"
)

raise HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Invalid input"
)

raise HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Not authorized"
)

# With logging
import logging
logger = logging.getLogger(__name__)

try:
    result = await some_operation()
except Exception as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Operation failed: {str(e)}"
    )
```

### File Operations

```python
from ..utils.async_fileio import (
    read_file_async,
    write_file_async,
    makedirs_async,
    walk_directory_async
)
from ..utils.resource_naming import get_project_path
import os

# Get project directory
project_path = os.path.abspath(get_project_path(user_id, project_id))

# Read file
content = await read_file_async(os.path.join(project_path, "file.txt"))

# Write file
await makedirs_async(os.path.dirname(file_path))
await write_file_async(file_path, content)

# List files
files = []
async for root, dirs, filenames in walk_directory_async(project_path):
    for filename in filenames:
        rel_path = os.path.relpath(
            os.path.join(root, filename),
            project_path
        )
        files.append(rel_path)
```

### Task Manager (Progress Tracking)

```python
from ..services.task_manager import get_task_manager

task_manager = get_task_manager()

# Create task
task = task_manager.create_task(
    task_id="setup-project-123",
    description="Setting up project"
)

# Update progress
task.update_progress(50, 100, "Copying files")

# Mark complete
task.update_progress(100, 100, "Complete")

# Get task status
task = task_manager.get_task("setup-project-123")
if task:
    return {
        "progress": task.progress,
        "total": task.total,
        "message": task.message,
        "status": task.status
    }
```

## Common Tasks

### Adding a New Router

1. Create router file in `orchestrator/app/routers/your_feature.py`
2. Define router with prefix and tags
3. Import in `orchestrator/app/main.py`
4. Include router in app: `app.include_router(your_feature.router)`
5. Create schemas in `orchestrator/app/schemas.py`
6. Write documentation in `docs/orchestrator/routers/your_feature.md`

### Adding an Endpoint to Existing Router

1. Define Pydantic schemas for request/response (if needed)
2. Add endpoint function with appropriate decorators
3. Implement business logic (or call service layer)
4. Add error handling and logging
5. Update router documentation
6. Write tests

### Implementing Background Tasks

1. For simple tasks, use FastAPI BackgroundTasks:
   ```python
   background_tasks.add_task(function, arg1, arg2)
   ```

2. For tasks needing progress tracking, use TaskManager:
   ```python
   task = task_manager.create_task(...)
   background_tasks.add_task(_perform_work, task, ...)
   ```

3. Client polls `/api/tasks/{task_id}` for progress

### Implementing Streaming

1. Define async generator function:
   ```python
   async def generate():
       for item in items:
           yield f"data: {json.dumps(item)}\n\n"
   ```

2. Return StreamingResponse:
   ```python
   return StreamingResponse(generate(), media_type="text/event-stream")
   ```

3. Client uses EventSource or fetch with streaming

## Architecture Notes

### Router Layer Responsibilities

Routers should:
- Handle HTTP concerns (request/response, status codes)
- Validate input using Pydantic schemas
- Authenticate and authorize requests
- Call service layer for business logic
- Format responses
- Handle errors gracefully

Routers should NOT:
- Contain complex business logic (use services)
- Directly manipulate files or external systems
- Make assumptions about deployment mode (Docker vs K8s)

### Service Layer Integration

Complex operations should be delegated to services:

```python
# Good: Delegate to service
from ..services.deployment.manager import DeploymentManager

deployment_manager = DeploymentManager(db)
deployment = await deployment_manager.create_deployment(
    project_id=project_id,
    provider="vercel",
    config=config
)

# Bad: Implement in router
# ... 200 lines of deployment logic ...
```

### Deployment Mode Awareness

Some operations differ between Docker and Kubernetes:

```python
from ..config import get_settings
settings = get_settings()

if settings.deployment_mode == "docker":
    # Use DockerComposeOrchestrator
    from ..services.docker_compose_orchestrator import DockerComposeOrchestrator
    orchestrator = DockerComposeOrchestrator(...)
elif settings.deployment_mode == "kubernetes":
    # Use KubernetesOrchestrator
    from ..services.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
    orchestrator = KubernetesOrchestrator(...)
```

The orchestrators abstract away the differences, providing a common interface.

## Testing

Run router tests:
```bash
pytest orchestrator/tests/test_routers/
```

Test specific router:
```bash
pytest orchestrator/tests/test_routers/test_projects.py -v
```

## Debugging

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
```

View logs in production:
```bash
# Docker
docker-compose logs -f backend

# Kubernetes (Minikube)
kubectl logs -f deployment/tesslate-backend -n tesslate

# Kubernetes (AWS EKS)
kubectl logs -f deployment/tesslate-backend -n tesslate
```

## Common Gotchas

### deployments.py - Build Trigger Parameters

When calling `DeploymentBuilder.trigger_build()`, ensure parameter names match exactly:

```python
# CORRECT
success, build_output = await builder.trigger_build(
    user_id=str(current_user.id),
    project_id=str(project.id),
    project_slug=project.slug,
    framework=framework,
    custom_build_command=None,  # NOT build_command
    container_name=container.container_name,
    volume_name=project.slug    # NOT working_directory
)

# WRONG - will cause unexpected keyword argument error
success, build_output = await builder.trigger_build(
    ...
    build_command=None,         # WRONG parameter name
    working_directory=path      # WRONG parameter name
)
```

## Examples

See individual router documentation files for detailed examples:
- `projects.md` - Project management workflows
- `chat.md` - Agent chat streaming
- `marketplace.md` - Agent publishing and purchasing
- `themes.md` - Theme API (public endpoints)
- `deployments.md` - External deployment workflows
- `billing.md` - Subscription and payment flows
