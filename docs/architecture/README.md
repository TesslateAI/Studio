# Tesslate Studio Architecture Documentation

This directory contains comprehensive documentation about Tesslate Studio's system architecture, component interactions, and deployment patterns.

## Overview

Tesslate Studio is an AI-powered web application builder that enables users to create, edit, deploy, and manage full-stack applications using natural language. The platform consists of a React frontend, FastAPI backend orchestrator, PostgreSQL database, and containerized user project environments.

## Documentation Structure

### Core Architecture Documents

1. **[system-overview.md](./system-overview.md)** - Complete system architecture
   - Technology stack breakdown
   - System component responsibilities
   - External service integrations
   - Security architecture (RBAC, Network Policies)
   - Visual reference: High-level architecture diagram

2. **[data-flow.md](./data-flow.md)** - Detailed request/response flows
   - User request lifecycle
   - Agent chat flow (user → agent → LLM → tools → response)
   - File operations flow (read/write through orchestrator)
   - Container operations flow (start/stop/status)
   - Git operations flow
   - Visual reference: Request flow and agent execution diagrams

3. **[deployment-modes.md](./deployment-modes.md)** - Deployment configurations
   - Docker mode (local development with Traefik)
   - Kubernetes mode (production with NGINX Ingress)
   - S3 Sandwich pattern (ephemeral storage + persistence)
   - Configuration differences and environment variables
   - Visual reference: Deployment pipeline diagram

### Supporting Documents

- **[CLAUDE.md](./CLAUDE.md)** - Agent context for understanding architecture
  - Quick reference for AI agents working with the codebase
  - Key source file locations
  - Links to related documentation
  - When to load this context

## Architecture Highlights

### Design Principles

1. **Non-Blocking Operations**
   - All long-running tasks use background workers or async processing
   - User requests never block on container startup, builds, or deployments
   - WebSocket streaming for real-time updates without polling

2. **Scalable Architecture**
   - Stateless backend services (horizontal scaling ready)
   - Database-based activity tracking (no in-memory state)
   - Per-project namespace isolation in Kubernetes
   - S3 Sandwich pattern for efficient storage management

3. **Container Isolation**
   - Each project runs in isolated Docker containers or K8s pods
   - Network policies enforce zero cross-project communication
   - Separate namespaces per project in Kubernetes mode
   - Pod affinity for multi-container projects sharing block storage

4. **Developer Experience**
   - Live preview with hot-reload for user projects
   - Monaco editor with IntelliSense and syntax highlighting
   - Real-time AI agent feedback via streaming responses
   - One-click deployments to Vercel, Netlify, Cloudflare

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Tesslate Studio                          │
├─────────────────────────────────────────────────────────────┤
│  Frontend (app/)           │   Orchestrator (orchestrator/) │
│  React + Vite + TypeScript │   FastAPI + Python             │
│  - Monaco Editor           │   - Auth (JWT/OAuth)           │
│  - Live Preview            │   - Project Management         │
│  - Chat UI                 │   - AI Agent System            │
│  - File Browser            │   - Container Orchestration    │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL        │  Docker/Kubernetes Container Manager   │
│  (User data,       │  (User project environments)           │
│   projects, chat)  │  - Per-project isolation               │
└─────────────────────────────────────────────────────────────┘
```

### Frontend (React)
- **Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/`
- **Tech**: React 19, TypeScript, Vite, Tailwind CSS
- **Responsibilities**: User interface, Monaco editor, live preview, chat UI
- **Key Files**:
  - `app/src/App.tsx` - Main application component
  - `app/src/lib/api.ts` - API client for backend communication

### Orchestrator (FastAPI)
- **Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/`
- **Tech**: FastAPI, Python 3.11, SQLAlchemy, LiteLLM
- **Responsibilities**: Authentication, project management, AI agent system, container orchestration
- **Key Files**:
  - `orchestrator/app/main.py` - FastAPI application entry point
  - `orchestrator/app/config.py` - Configuration and settings
  - `orchestrator/app/models.py` - Database models
  - `orchestrator/app/routers/` - API endpoint handlers
  - `orchestrator/app/agent/` - AI agent system
  - `orchestrator/app/services/orchestration/` - Container orchestration

### Database (PostgreSQL)
- **Tech**: PostgreSQL with asyncpg driver
- **Responsibilities**: User accounts, projects, chat history, subscriptions
- **Key Models**: User, Project, Container, Chat, Message, MarketplaceAgent

### Container Runtime
- **Docker Mode**: Docker Compose + Traefik (local development)
  - Includes `devserver` build-only service for building the devserver image
- **Kubernetes Mode**: K8s + NGINX Ingress (production)
  - All base deployments use `revisionHistoryLimit: 3`
  - AWS overlays split into `aws-base`, `aws-beta`, `aws-production`
- **Responsibilities**: Running user project environments in isolation

## How Systems Interact

1. **User Authentication**
   - Frontend → OAuth provider (GitHub/Google)
   - OAuth callback → Backend `/api/auth/{provider}/callback`
   - Backend generates JWT/Cookie → Frontend stores credentials

2. **Project Creation**
   - Frontend → `POST /api/projects` → Backend
   - Backend creates DB record + project directory
   - Background task sets up container environment
   - Frontend polls status or receives WebSocket updates

3. **AI Agent Chat**
   - Frontend → `POST /api/chat/stream` → Backend
   - Backend creates agent instance from config
   - Agent streams LLM responses + tool executions
   - Frontend displays real-time updates in chat UI

4. **Container Operations**
   - Frontend → `POST /api/projects/{id}/start` → Backend
   - Backend calls orchestrator (Docker/K8s)
   - Orchestrator creates containers/pods + ingress rules
   - User project becomes accessible at subdomain

5. **File Operations**
   - Frontend → `GET/POST /api/projects/{id}/files` → Backend
   - Backend reads/writes files in project directory
   - Docker mode: Direct filesystem access
   - K8s mode: Exec into file-manager pod

## Related Documentation

- **System-Specific Architecture**:
  - [Frontend Architecture](../app/CLAUDE.md)
  - [Orchestrator Architecture](../orchestrator/CLAUDE.md)
  - [Infrastructure Setup](../infrastructure/CLAUDE.md)

- **Operations Guides**:
  - [Deployment Guide](../guides/deployment.md)
  - [Development Setup](../guides/development.md)
  - [Troubleshooting](../guides/troubleshooting.md)

- **Kubernetes Deep Dive**:
  - [K8s Architecture](../../k8s/ARCHITECTURE.md)
  - [K8s Quickstart](../../k8s/QUICKSTART.md)

## Quick Reference

### Deployment Modes

| Mode | Use Case | Routing | Storage |
|------|----------|---------|---------|
| `docker` | Local development | Traefik (*.localhost) | Local filesystem |
| `kubernetes` | Production | NGINX Ingress | S3 + PVC (S3 Sandwich) |

### Key Environment Variables

```bash
# Deployment Mode
DEPLOYMENT_MODE=docker  # or kubernetes

# Docker Mode
DEV_SERVER_BASE_URL=http://localhost

# Kubernetes Mode
K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
K8S_USE_S3_STORAGE=true
K8S_STORAGE_CLASS=tesslate-block-storage
S3_ENDPOINT_URL=https://s3.us-east-1.amazonaws.com
S3_BUCKET_NAME=tesslate-project-storage-prod
```

### Key Source Files

| Component | File Path |
|-----------|-----------|
| Backend Entry | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/main.py` |
| Backend Config | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/config.py` |
| Frontend Entry | `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/App.tsx` |
| API Client | `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/api.ts` |
| K8s Orchestrator | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py` |
| Agent System | `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/stream_agent.py` |

## Contributing

When modifying the architecture:

1. Update the relevant markdown files in this directory
2. Update diagrams in `diagrams/` folder (when created)
3. Update system-specific CLAUDE.md files
4. Ensure changes are non-blocking and scalable
5. Update tests to reflect architectural changes

## Getting Started

New to Tesslate Studio? Start here:

1. Read [system-overview.md](./system-overview.md) for high-level understanding
2. Review [deployment-modes.md](./deployment-modes.md) for your deployment target
3. Check [data-flow.md](./data-flow.md) for request/response patterns
4. Set up your environment using [../guides/development.md](../guides/development.md)
5. Deploy using [../guides/deployment.md](../guides/deployment.md)
