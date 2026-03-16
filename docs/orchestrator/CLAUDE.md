# Orchestrator Agent Context

## Purpose

The orchestrator is Tesslate Studio's FastAPI backend handling all API requests, AI agent execution, and container orchestration. Load this context when working on any backend functionality.

## Key Source Files

| File | Purpose |
|------|---------|
| [main.py](../../orchestrator/app/main.py) | FastAPI app entry, middleware, router registration |
| [config.py](../../orchestrator/app/config.py) | All configuration via Pydantic BaseSettings |
| [models.py](../../orchestrator/app/models.py) | 45+ SQLAlchemy database models |
| [database.py](../../orchestrator/app/database.py) | Async SQLAlchemy engine setup |
| [schemas.py](../../orchestrator/app/schemas.py) | Pydantic request/response schemas |
| [worker.py](../../orchestrator/app/worker.py) | ARQ worker for distributed agent execution |
| [auth_external.py](../../orchestrator/app/auth_external.py) | API key authentication for external agent API |
| [services/skill_discovery.py](../../orchestrator/app/services/skill_discovery.py) | Skill discovery and loading for agents |
| [services/channels/](../../orchestrator/app/services/channels/) | Messaging channel integrations (Telegram, Slack, Discord, WhatsApp) |
| [services/mcp/](../../orchestrator/app/services/mcp/) | MCP client, bridge, and server manager |

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
│   ├── channels.py   # Messaging channel config
│   ├── mcp.py        # User MCP server management
│   └── mcp_server.py # MCP server marketplace catalog
├── services/         # Business logic (30+ files)
│   ├── skill_discovery.py  # Skill discovery & loading
│   ├── channels/     # Channel integrations (Telegram, Slack, Discord, WhatsApp)
│   └── mcp/          # MCP client, bridge, manager
├── seeds/            # Database seed data
│   ├── skills.py     # Marketplace skills (15+)
│   └── marketplace_agents.py # Marketplace agents
└── agent/            # AI system
    └── tools/        # Agent tools
        ├── web_ops/  # Web search, fetch, send_message
        └── skill_ops/ # Skill loading
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
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` |
| `WEB_SEARCH_PROVIDER` | Web search backend | `tavily` |
| `TAVILY_API_KEY` | Tavily search API key | `tvly-...` |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key | `BSA...` |
| `AGENT_DISCORD_WEBHOOK_URL` | Discord webhook for agent messaging | `https://discord.com/api/webhooks/...` |
| `CHANNEL_ENCRYPTION_KEY` | Fernet key for channel credentials | Base64-encoded key |
| `MCP_TOOL_CACHE_TTL` | MCP schema cache TTL (seconds) | `300` |
| `MCP_TOOL_TIMEOUT` | MCP tool call timeout (seconds) | `30` |
| `MCP_MAX_SERVERS_PER_USER` | Max MCP servers per user | `20` |

### Key Routers

| Router | Base Path | Purpose |
|--------|-----------|---------|
| projects | `/api/projects` | Project CRUD, files, containers, setup-config |
| chat | `/api/chat` | Agent chat, streaming |
| two_fa | `/api/auth` | Email 2FA login, verification, password reset |
| marketplace | `/api/marketplace` | Agent/base/skill/MCP marketplace |
| billing | `/api/billing` | Subscriptions, credits |
| git | `/api/git` | Git operations |
| external_agent | `/api/external` | External agent API (API key auth, SSE events) |
| channels | `/api/channels` | Messaging channel configuration (Telegram, Slack, Discord, WhatsApp) |
| mcp | `/api/mcp` | User MCP server management and tool execution |
| mcp_server | `/api/mcp-servers` | MCP server marketplace catalog |

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

## BANNED: Deriving K8s Resource Names from Container Names

**NEVER** fall back to `container.name` when `container.directory` is `"."`, empty, or `None`. This pattern is **strictly banned**:

```python
# BAD — BANNED — DO NOT USE
raw_dir = container.directory if container.directory not in (".", "", None) else container.name
container_dir = _sanitize_k8s_name(raw_dir)

# Also banned in any form:
dir_for_name = container.name if container.directory in (".", "", None) else container.directory
sib_dir = sibling.directory if sibling.directory not in (".", "", None) else sibling.name
```

**Why**: `container.name` and `container.directory` are independent fields set by the config file (`.tesslate/config.json`). Computing one from the other creates a fragile, implicit coupling that breaks when names or directories are renamed independently. The config file is the **sole source of truth**.

**Recommended: Read URLs from live K8s state**

When you need a container's URL (e.g., fast paths, status checks), read it from the actual K8s pods via `get_project_status()`. The pod labels (`tesslate.io/container-directory`) are the ground truth for what identifiers were used during deployment:

```python
# GOOD — Read from K8s state, no recomputation
orchestrator = get_orchestrator()
status = await orchestrator.get_project_status(project.slug, project.id)
if status.get("status") == "active":
    for _dir, info in status.get("containers", {}).items():
        if info.get("container_id") == str(container.id):
            url = info["url"]  # Built from actual pod labels
            break
```

**When you must resolve directory → K8s name** (e.g., inside `start_environment()` during initial creation), use `container.directory` directly — never substitute `container.name`:

```python
# ACCEPTABLE — Uses directory directly, handles "." explicitly
container_directory = _sanitize_k8s_name(container.directory)
if not container_directory:  # "." sanitizes to ""
    # Handle root-directory containers explicitly — do NOT fall back to container.name
    ...
```

## Common Gotchas

1. **Image caching**: Use `--no-cache` when building Docker images
2. **K8s permissions**: Backend needs ClusterRole for namespace management
3. **CORS**: Wildcard subdomains require regex pattern matching
4. **WebSocket**: Different auth flow than HTTP (token in query param)
