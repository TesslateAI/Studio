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
│   ├── models.py            # Database models (45+ classes)
│   ├── schemas.py           # Pydantic schemas
│   ├── database.py          # SQLAlchemy setup
│   │
│   ├── routers/             # API endpoints
│   │   ├── projects.py      # Project CRUD, files, containers, setup-config
│   │   ├── chat.py          # Agent chat, streaming
│   │   ├── marketplace.py   # Agent/base/skill/MCP marketplace
│   │   ├── channels.py      # Messaging channel configuration
│   │   ├── mcp.py           # User MCP server management
│   │   ├── mcp_server.py    # MCP server marketplace catalog
│   │   └── ...              # 20+ more routers
│   │
│   ├── services/            # Business logic
│   │   ├── orchestration/   # Container management
│   │   │   ├── base.py      # Abstract orchestrator
│   │   │   ├── docker.py    # Docker Compose mode
│   │   │   └── kubernetes_orchestrator.py  # K8s mode
│   │   ├── s3_manager.py    # S3 sandwich pattern
│   │   ├── skill_discovery.py # Skill discovery and loading
│   │   ├── channels/        # Messaging channel integrations
│   │   │   ├── base.py      # Abstract channel interface
│   │   │   ├── telegram.py  # Telegram bot integration
│   │   │   ├── slack.py     # Slack integration
│   │   │   ├── discord_bot.py # Discord webhook integration
│   │   │   ├── whatsapp.py  # WhatsApp integration
│   │   │   ├── formatting.py # Cross-platform message formatting
│   │   │   └── registry.py  # Channel provider registry
│   │   ├── mcp/             # Model Context Protocol
│   │   │   ├── client.py    # MCP client for server communication
│   │   │   ├── bridge.py    # Bridge MCP tools into agent tool registry
│   │   │   └── manager.py   # MCP server lifecycle management
│   │   └── ...              # 30+ services
│   │
│   ├── seeds/               # Database seed data
│   │   ├── skills.py        # Marketplace skills (15+ open-source + Tesslate)
│   │   └── marketplace_agents.py # Marketplace agents
│   │
│   └── agent/               # AI agent system
│       ├── base.py          # AbstractAgent
│       ├── stream_agent.py  # Streaming agent
│       ├── factory.py       # Agent creation
│       └── tools/           # Agent tools
│           ├── web_ops/     # Web search, fetch, send_message
│           │   ├── search.py     # Multi-provider web search
│           │   ├── fetch.py      # HTTP fetch tool
│           │   ├── send_message.py # Messaging channel tool
│           │   └── providers.py  # Search provider implementations
│           └── skill_ops/   # Skill tools
│               └── load_skill.py # Load skill at runtime
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
| [config.py](../../orchestrator/app/config.py) | ~490 | All configuration settings (env vars) |
| [models.py](../../orchestrator/app/models.py) | ~1800 | 45+ SQLAlchemy database models |
| [routers/projects.py](../../orchestrator/app/routers/projects.py) | 5142+ | Core project management API, setup-config |
| [routers/chat.py](../../orchestrator/app/routers/chat.py) | 2044 | Agent chat and streaming |
| [routers/channels.py](../../orchestrator/app/routers/channels.py) | - | Messaging channel CRUD and webhook |
| [routers/mcp.py](../../orchestrator/app/routers/mcp.py) | - | User MCP server install/config/execute |
| [routers/mcp_server.py](../../orchestrator/app/routers/mcp_server.py) | - | MCP server marketplace catalog |
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
     │                                      ├── Agent System (for /chat)
     │                                      │    ├── LLM + Tools
     │                                      │    ├── Skills (loaded at runtime)
     │                                      │    ├── MCP Tools (bridged from MCP servers)
     │                                      │    └── Web Search (Tavily/Brave/DuckDuckGo)
     │                                      │
     │                                      ├── Channel System (for /channels)
     │                                      │    └── Telegram/Slack/Discord/WhatsApp
     │                                      │
     │                                      └── MCP System (for /mcp)
     │                                           └── MCP Server lifecycle + tool execution
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
| `WEB_SEARCH_PROVIDER` | Search backend (tavily/brave/duckduckgo) |
| `TAVILY_API_KEY` | Tavily search API key |
| `CHANNEL_ENCRYPTION_KEY` | Fernet key for channel credentials |
| `MCP_TOOL_TIMEOUT` | MCP tool call timeout (seconds) |

## Common Tasks

| Task | Location |
|------|----------|
| Add API endpoint | [routers/](routers/README.md) |
| Add business logic | [services/](services/README.md) |
| Add agent tool | [agent/tools/](agent/tools/README.md) |
| Add database model | [models/](models/README.md) |
| Change container behavior | [orchestration/](orchestration/README.md) |
| Add messaging channel | `services/channels/` - implement `base.py` interface |
| Add MCP integration | `services/mcp/` - client, bridge, manager |
| Add marketplace skill | `seeds/skills.py` - add to OPENSOURCE_SKILLS or TESSLATE_SKILLS |

## Related Documentation

- [Architecture Overview](../architecture/README.md)
- [Request Flow Diagram](../architecture/diagrams/request-flow.mmd)
- [Agent Execution Diagram](../architecture/diagrams/agent-execution.mmd)
