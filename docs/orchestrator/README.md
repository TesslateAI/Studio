# Orchestrator (Backend)

> FastAPI backend powering Tesslate Studio's API, AI agents, and container orchestration

## Overview

The orchestrator is the heart of Tesslate Studio - a FastAPI application that:
- Serves REST API endpoints for the frontend
- Manages AI agent execution and tool calls
- Orchestrates Docker/Kubernetes containers for user projects
- Handles authentication, billing, and external integrations

## Architecture

```
orchestrator/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Configuration settings
│   ├── models.py            # Database models (39 classes)
│   ├── schemas.py           # Pydantic schemas
│   ├── database.py          # SQLAlchemy setup
│   │
│   ├── routers/             # API endpoints
│   │   ├── projects.py      # Project CRUD, files, containers (5142 lines)
│   │   ├── chat.py          # Agent chat, streaming (2044 lines)
│   │   ├── marketplace.py   # Agent/base marketplace (2417 lines)
│   │   └── ...              # 20+ more routers
│   │
│   ├── services/            # Business logic
│   │   ├── orchestration/   # Container management
│   │   │   ├── base.py      # Abstract orchestrator
│   │   │   ├── docker.py    # Docker Compose mode
│   │   │   └── kubernetes_orchestrator.py  # K8s mode
│   │   ├── s3_manager.py    # S3 sandwich pattern
│   │   └── ...              # 30+ services
│   │
│   └── agent/               # AI agent system
│       ├── base.py          # AbstractAgent
│       ├── stream_agent.py  # Streaming agent
│       ├── factory.py       # Agent creation
│       └── tools/           # Agent tools (bash, read/write, etc.)
│
├── Dockerfile               # Backend image
├── Dockerfile.devserver     # User project container image
└── pyproject.toml           # Python dependencies
```

## Quick Navigation

| Section | Description |
|---------|-------------|
| [Routers](routers/README.md) | API endpoints - where requests are handled |
| [Services](services/README.md) | Business logic - where work gets done |
| [Agent](agent/README.md) | AI agent system - LLM + tools |
| [Models](models/README.md) | Database models - data structure |
| [Orchestration](orchestration/README.md) | Container management - Docker/K8s |

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| [main.py](../../orchestrator/app/main.py) | ~700 | Entry point, middleware, router registration |
| [config.py](../../orchestrator/app/config.py) | ~200 | All configuration settings (env vars) |
| [models.py](../../orchestrator/app/models.py) | ~1000 | 39 SQLAlchemy database models |
| [routers/projects.py](../../orchestrator/app/routers/projects.py) | 5142 | Core project management API |
| [routers/chat.py](../../orchestrator/app/routers/chat.py) | 2044 | Agent chat and streaming |
| [agent/stream_agent.py](../../orchestrator/app/agent/stream_agent.py) | ~150 | Streaming AI agent implementation |

## Technology Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| Python | 3.11 |
| ORM | SQLAlchemy (async) |
| Database | PostgreSQL (asyncpg) |
| Validation | Pydantic v2 |
| Auth | FastAPI-Users + JWT |
| AI | LiteLLM (multi-provider) |

## Request Flow

```
HTTP Request → Middleware (Auth, CORS) → Router → Service → Database/External
     │                                      │
     │                                      └── Agent System (for /chat)
     │                                           └── LLM + Tools
     │
     └── Response (JSON/Streaming)
```

## Getting Started

### Run Locally (Docker)

```bash
# From project root
docker-compose up orchestrator
```

### Run Locally (Direct)

```bash
cd orchestrator
pip install -e .
uvicorn app.main:app --reload --port 8000
```

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection |
| `SECRET_KEY` | JWT signing |
| `DEPLOYMENT_MODE` | `docker` or `kubernetes` |
| `LITELLM_API_BASE` | LLM API endpoint |
| `APP_DOMAIN` | Application domain |

## Common Tasks

| Task | Location |
|------|----------|
| Add API endpoint | [routers/](routers/README.md) |
| Add business logic | [services/](services/README.md) |
| Add agent tool | [agent/tools/](agent/tools/README.md) |
| Add database model | [models/](models/README.md) |
| Change container behavior | [orchestration/](orchestration/README.md) |

## Related Documentation

- [Architecture Overview](../architecture/README.md)
- [Request Flow Diagram](../architecture/diagrams/request-flow.mmd)
- [Agent Execution Diagram](../architecture/diagrams/agent-execution.mmd)
