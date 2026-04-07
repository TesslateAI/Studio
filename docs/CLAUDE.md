# Tesslate Studio - Root Agent Context

## Purpose

This is the root context for Tesslate Studio, an AI-powered web application builder. Load this context when you need a high-level understanding of the entire system or don't know where to start.

## System Overview

Tesslate Studio consists of four major systems:

| System | Purpose | Technology |
|--------|---------|------------|
| **Orchestrator** | Backend API, AI agents, container management | FastAPI, Python 3.11 |
| **App** | Frontend UI, code editor, chat interface | React 19, TypeScript |
| **Infrastructure** | Kubernetes, Docker, Terraform | K8s, Kustomize, AWS |
| **Database** | User data, projects, chat history | PostgreSQL |
| **Redis** | Pub/sub, task queue, caching, distributed locks | Redis 7.x |

## Key Source Files

| File | Purpose |
|------|---------|
| [orchestrator/app/main.py](../orchestrator/app/main.py) | Backend entry point, middleware, routers |
| [orchestrator/app/config.py](../orchestrator/app/config.py) | All configuration settings |
| [orchestrator/app/models.py](../orchestrator/app/models.py) | Database models (45+ classes) |
| [app/src/App.tsx](../app/src/App.tsx) | Frontend router and auth |
| [app/src/lib/api.ts](../app/src/lib/api.ts) | API client (1300+ lines) |
| [docker-compose.yml](../docker-compose.yml) | Local development stack |
| [k8s/base/kustomization.yaml](../k8s/base/kustomization.yaml) | Kubernetes base config |
| [orchestrator/app/worker.py](../orchestrator/app/worker.py) | ARQ worker for distributed agent execution |
| [orchestrator/app/routers/external_agent.py](../orchestrator/app/routers/external_agent.py) | External agent API |
| [orchestrator/app/routers/channels.py](../orchestrator/app/routers/channels.py) | Messaging channel configuration |
| [orchestrator/app/routers/mcp.py](../orchestrator/app/routers/mcp.py) | User MCP server management |
| [orchestrator/app/routers/mcp_server.py](../orchestrator/app/routers/mcp_server.py) | MCP server marketplace catalog |
| [orchestrator/app/services/skill_discovery.py](../orchestrator/app/services/skill_discovery.py) | Skill discovery and loading |
| [orchestrator/app/services/channels/](../orchestrator/app/services/channels/) | Channel integrations (Telegram, Slack, Discord, WhatsApp) |
| [orchestrator/app/services/mcp/](../orchestrator/app/services/mcp/) | MCP client, bridge, and manager |

## Related Contexts (Load These For)

| Context | When to Load |
|---------|--------------|
| [architecture/CLAUDE.md](architecture/CLAUDE.md) | Understanding system design, data flows |
| [orchestrator/CLAUDE.md](orchestrator/CLAUDE.md) | Backend development, API changes |
| [app/CLAUDE.md](app/CLAUDE.md) | Frontend development, UI changes |
| [infrastructure/CLAUDE.md](infrastructure/CLAUDE.md) | Kubernetes, Docker, deployment |

## Quick Reference

### Deployment Modes

| Mode | Config Value | Use Case |
|------|--------------|----------|
| Docker | `DEPLOYMENT_MODE=docker` | Local development |
| Kubernetes | `DEPLOYMENT_MODE=kubernetes` | Production (Minikube, EKS) |

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | JWT signing key |
| `LITELLM_API_BASE` | LLM API endpoint |
| `S3_BUCKET_NAME` | Project storage bucket |
| `APP_DOMAIN` | Application domain (localhost, your-domain.com) |
| `SMTP_HOST` | SMTP server for email (2FA codes, password resets) |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SMTP_USERNAME` | SMTP authentication username |
| `SMTP_PASSWORD` | SMTP authentication password |
| `SMTP_SENDER_EMAIL` | Sender email address (e.g., noreply@domain.com) |
| `TWO_FA_ENABLED` | Enable email 2FA for logins (default: false) |
| `REDIS_URL` | Redis connection string (cross-pod comms) |
| `WEB_SEARCH_PROVIDER` | Web search provider: tavily, brave, duckduckgo |
| `TAVILY_API_KEY` | Tavily API key for web search |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key |
| `AGENT_DISCORD_WEBHOOK_URL` | Discord webhook for agent send_message tool |
| `CHANNEL_ENCRYPTION_KEY` | Fernet key for channel credential encryption |
| `MCP_TOOL_CACHE_TTL` | MCP tool schema cache TTL in seconds (default: 300) |
| `MCP_TOOL_TIMEOUT` | MCP tool call timeout in seconds (default: 30) |
| `MCP_MAX_SERVERS_PER_USER` | Max MCP servers per user (default: 20) |

### Project URL Patterns

| Mode | Pattern | Example |
|------|---------|---------|
| Docker | `{container}.localhost` | `frontend.localhost` |
| K8s Minikube | `{container}.localhost` | `frontend.localhost` |
| K8s AWS | `{container}.{project-slug}.your-domain.com` | `frontend.my-app-k3x8n2.your-domain.com` |

### Common Commands

```bash
# Docker setup from scratch
cp .env.example .env           # configure required values
docker compose up --build -d   # build and start all services
docker compose ps              # verify services are healthy

# Docker clean slate reset
docker compose down --volumes --remove-orphans
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep -i tesslate | awk '{print $2}' | sort -u | xargs docker rmi -f
docker compose up --build -d

# Minikube deployment
kubectl apply -k k8s/overlays/minikube

# AWS EKS deployment
kubectl apply -k k8s/overlays/aws

# Build backend image
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Build frontend image
docker build -t tesslate-frontend:latest -f app/Dockerfile.prod app/

# Seed database (after first startup or clean slate reset)
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_bases.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_agents.py
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_opensource_agents.py
# See CLAUDE.md "Database Seeding" section for full instructions including themes
```

## Architecture Diagrams

| Diagram | Description |
|---------|-------------|
| [high-level-architecture.mmd](architecture/diagrams/high-level-architecture.mmd) | Complete system overview |
| [request-flow.mmd](architecture/diagrams/request-flow.mmd) | API request lifecycle |
| [agent-execution.mmd](architecture/diagrams/agent-execution.mmd) | AI agent execution flow |
| [container-lifecycle.mmd](architecture/diagrams/container-lifecycle.mmd) | Project container management |

## When to Load This Context

Load this root CLAUDE.md when:
- Starting work on Tesslate Studio for the first time
- Need to understand how systems connect
- Looking for the right subsystem to modify
- Debugging cross-system issues
- Need quick reference to key files and commands

## Navigation Guide

### "I need to..."

| Task | Go To |
|------|-------|
| Email 2FA & password reset | [app/pages/auth.md](app/pages/auth.md) |
| Set up Docker from scratch | [guides/docker-setup.md](guides/docker-setup.md) |
| Seed the database | [guides/docker-setup.md](guides/docker-setup.md) (Step 6) or root [CLAUDE.md](../CLAUDE.md) "Database Seeding" |
| Run database migrations | [guides/database-migrations.md](guides/database-migrations.md) |
| Add a new API endpoint | [orchestrator/routers/CLAUDE.md](orchestrator/routers/CLAUDE.md) |
| Modify the AI agent | [orchestrator/agent/CLAUDE.md](orchestrator/agent/CLAUDE.md) |
| Add a new tool for the agent | [orchestrator/agent/tools/CLAUDE.md](orchestrator/agent/tools/CLAUDE.md) |
| Change container behavior | [orchestrator/orchestration/CLAUDE.md](orchestrator/orchestration/CLAUDE.md) |
| Credit system & billing | [orchestrator/services/credit-system.md](orchestrator/services/credit-system.md) |
| Model pricing | [orchestrator/services/model-pricing.md](orchestrator/services/model-pricing.md) |
| Modify the chat UI | [app/components/chat/CLAUDE.md](app/components/chat/CLAUDE.md) |
| Change the code editor | [app/components/editor/CLAUDE.md](app/components/editor/CLAUDE.md) |
| Fix Kubernetes issues | [infrastructure/kubernetes/CLAUDE.md](infrastructure/kubernetes/CLAUDE.md) |
| Update Minikube config | [infrastructure/kubernetes/overlays/CLAUDE.md](infrastructure/kubernetes/overlays/CLAUDE.md) |
| Deploy to AWS | [guides/aws-deployment.md](guides/aws-deployment.md) |
| Understand real-time agent system | [guides/real-time-agent-architecture.md](guides/real-time-agent-architecture.md) |
| External agent API | [orchestrator/routers/external-agent.md](orchestrator/routers/external-agent.md) |
| Redis/pub-sub infrastructure | [orchestrator/services/pubsub.md](orchestrator/services/pubsub.md) |
| Skills system | [orchestrator/agent/CLAUDE.md](orchestrator/agent/CLAUDE.md) |
| Messaging channels | [orchestrator/routers/CLAUDE.md](orchestrator/routers/CLAUDE.md) → channels.py |
| Gateway & messaging platforms | [orchestrator/routers/CLAUDE.md](orchestrator/routers/CLAUDE.md) → gateway.py, schedules.py |
| Agent scheduling (cron) | [orchestrator/agent/tools/CLAUDE.md](orchestrator/agent/tools/CLAUDE.md) → schedule_ops |
| MCP server integration | [orchestrator/routers/CLAUDE.md](orchestrator/routers/CLAUDE.md) → mcp.py, mcp_server.py |
| Web search tool | [orchestrator/agent/tools/CLAUDE.md](orchestrator/agent/tools/CLAUDE.md) |
| Universal project setup | [orchestrator/routers/CLAUDE.md](orchestrator/routers/CLAUDE.md) → projects.py setup-config |

## Important Notes

1. **Non-blocking**: All changes should be non-blocking to prevent holding up other users
2. **Scalable solutions**: Fix issues in a general, scalable way for future cases
3. **No hardcoding**: Avoid hardcoded values; use configuration
4. **Security**: Check for OWASP top 10 vulnerabilities in code changes
5. **Image updates**: Always use `--no-cache` when building Docker images for Minikube
