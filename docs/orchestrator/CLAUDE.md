# Orchestrator Agent Context

## Purpose

The orchestrator is Tesslate Studio's FastAPI backend handling all API requests, AI agent execution, and container orchestration. Load this context when working on any backend functionality.

## Key Source Files

| File | Purpose |
|------|---------|
| [main.py](../../orchestrator/app/main.py) | FastAPI app entry, middleware, router registration |
| [config.py](../../orchestrator/app/config.py) | All configuration via Pydantic BaseSettings |
| [models.py](../../orchestrator/app/models.py) | 39 SQLAlchemy database models |
| [database.py](../../orchestrator/app/database.py) | Async SQLAlchemy engine setup |
| [schemas.py](../../orchestrator/app/schemas.py) | Pydantic request/response schemas |

## Related Contexts (Load These For)

| Context | When |
|---------|------|
| [routers/CLAUDE.md](routers/CLAUDE.md) | Adding/modifying API endpoints |
| [services/CLAUDE.md](services/CLAUDE.md) | Business logic changes |
| [agent/CLAUDE.md](agent/CLAUDE.md) | AI agent behavior |
| [agent/tools/CLAUDE.md](agent/tools/CLAUDE.md) | Adding agent tools |
| [models/CLAUDE.md](models/CLAUDE.md) | Database schema changes |
| [orchestration/CLAUDE.md](orchestration/CLAUDE.md) | Container management |
| [../infrastructure/kubernetes/CLAUDE.md](../infrastructure/kubernetes/CLAUDE.md) | K8s deployment issues |

## Quick Reference

### Project Structure

```
orchestrator/app/
├── main.py           # Entry point
├── config.py         # Settings
├── models.py         # DB models
├── routers/          # API endpoints (25+ files)
├── services/         # Business logic (30+ files)
└── agent/            # AI system
    └── tools/        # Agent tools
```

### Common Patterns

**Async Database Session**
```python
from app.database import get_db

@router.get("/items")
async def get_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Item))
    return result.scalars().all()
```

**Current User Dependency**
```python
from app.users import current_active_user

@router.get("/me")
async def get_me(user: User = Depends(current_active_user)):
    return user
```

**Background Task**
```python
from fastapi import BackgroundTasks

@router.post("/start")
async def start(background_tasks: BackgroundTasks):
    background_tasks.add_task(long_running_task, arg1, arg2)
    return {"status": "started"}
```

**Orchestrator Pattern**
```python
from app.services.orchestration.factory import get_orchestrator

orchestrator = get_orchestrator()
await orchestrator.start_project(project, containers, connections, user_id, db)
```

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL async URL | `postgresql+asyncpg://user:pass@host/db` |
| `SECRET_KEY` | JWT signing key | Random 32+ char string |
| `DEPLOYMENT_MODE` | `docker` or `kubernetes` | `kubernetes` |
| `APP_DOMAIN` | Base domain | `your-domain.com` |
| `LITELLM_API_BASE` | LLM proxy URL | `http://litellm:8000` |
| `S3_BUCKET_NAME` | Project storage | `tesslate-projects-prod` |

### Key Routers

| Router | Base Path | Purpose |
|--------|-----------|---------|
| projects | `/api/projects` | Project CRUD, files, containers |
| chat | `/api/chat` | Agent chat, streaming |
| two_fa | `/api/auth` | Email 2FA login, verification, password reset |
| marketplace | `/api/marketplace` | Agent/base marketplace |
| billing | `/api/billing` | Subscriptions, credits |
| git | `/api/git` | Git operations |

### Middleware Stack (Order Matters)

1. **ProxyHeadersMiddleware** - Handle X-Forwarded-* headers
2. **DynamicCORSMiddleware** - CORS with wildcard subdomains
3. **CSRFProtectionMiddleware** - CSRF token validation
4. **Security Headers** - CSP, X-Content-Type-Options

## When to Load This Context

Load this CLAUDE.md when:
- Starting backend development
- Understanding the overall backend architecture
- Debugging request flow issues
- Adding new routers or services
- Modifying authentication/authorization

## Important Notes

1. **Non-blocking**: Use `BackgroundTasks` for long operations
2. **Async everywhere**: All database operations must be async
3. **Factory pattern**: Use `get_orchestrator()` for container ops
4. **Mode-agnostic**: Code should work in both Docker and K8s modes
5. **Error handling**: Use HTTPException with appropriate status codes

## Common Gotchas

1. **Image caching**: Use `--no-cache` when building Docker images
2. **K8s permissions**: Backend needs ClusterRole for namespace management
3. **CORS**: Wildcard subdomains require regex pattern matching
4. **WebSocket**: Different auth flow than HTTP (token in query param)
