# Tesslate Studio Documentation

> Comprehensive technical documentation for Tesslate Studio - an AI-powered web application builder

## What is Tesslate Studio?

Tesslate Studio is an AI-powered web application builder that lets users create, edit, deploy, and manage full-stack applications using natural language. Users describe what they want, an AI agent writes the code, and the platform handles containerized deployment.

## Quick Navigation

| Section | Description | Start Here |
|---------|-------------|------------|
| [Architecture](architecture/README.md) | High-level system design, data flows, diagrams | Understanding the system |
| [Orchestrator](orchestrator/README.md) | FastAPI backend, API endpoints, services | Backend development |
| [App](app/README.md) | React frontend, components, state management | Frontend development |
| [Infrastructure](infrastructure/README.md) | Kubernetes, Docker, Terraform | DevOps & deployment |
| [Guides](guides/README.md) | How-to guides, troubleshooting | Getting started |

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Tesslate Studio                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────┐          ┌──────────────────────────────────┐ │
│  │   Frontend (app/)    │          │     Orchestrator (orchestrator/) │ │
│  │   React + Vite       │  ◄────►  │     FastAPI + Python              │ │
│  │   TypeScript         │   API    │                                   │ │
│  │                      │          │  ┌─────────────────────────────┐  │ │
│  │  • Monaco Editor     │          │  │     AI Agent System         │  │ │
│  │  • Live Preview      │          │  │  • StreamAgent              │  │ │
│  │  • Chat UI           │          │  │  • IterativeAgent           │  │ │
│  │  • File Browser      │          │  │  • Tool Registry            │  │ │
│  │  • Graph Canvas      │          │  └─────────────────────────────┘  │ │
│  └──────────────────────┘          │                                   │ │
│                                    │  ┌─────────────────────────────┐  │ │
│                                    │  │   Container Orchestration   │  │ │
│                                    │  │  • Docker Compose (dev)     │  │ │
│                                    │  │  • Kubernetes (prod)        │  │ │
│                                    │  │  • S3 Sandwich Pattern      │  │ │
│                                    │  └─────────────────────────────┘  │ │
│                                    └──────────────────────────────────┘ │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                        Data Layer                                 │   │
│  │  PostgreSQL (users, projects, chat)   S3/MinIO (project files)   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     Real-Time Layer                              │   │
│  │  Redis (pub/sub, streams, task queue, caching)                  │   │
│  │  ARQ Worker (distributed agent execution)                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     External Services                             │   │
│  │  LiteLLM (AI)   Stripe (billing)   OAuth (GitHub/Google)         │   │
│  │  SMTP Email (2FA, password reset)                                │   │
│  │  Vercel/Netlify/Cloudflare (external deployment)                 │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | React 19, TypeScript, Vite, Tailwind CSS, Monaco Editor, XYFlow |
| **Backend** | FastAPI, Python 3.11, SQLAlchemy, Pydantic |
| **Database** | PostgreSQL (asyncpg) |
| **AI/LLM** | LiteLLM → OpenAI, Anthropic, Qwen models |
| **Containers** | Docker Compose (dev), Kubernetes (prod) |
| **Storage** | AWS S3 / MinIO (project hibernation) |
| **Task Queue** | Redis, ARQ (distributed agent execution) |
| **Routing** | Traefik (Docker), NGINX Ingress (K8s) |
| **Payments** | Stripe |

## Key Concepts

### 1. AI Agent System
The heart of Tesslate Studio. Agents receive user requests, call LLMs with system prompts and tools, and execute code changes.

- **StreamAgent**: Real-time streaming responses
- **IterativeAgent**: Multi-step tool execution
- **ReActAgent**: Reasoning + Acting pattern
- **TesslateAgent**: Production agent with native function calling, trajectory recording, planning mode, subagents, and context compaction

See: [Agent Documentation](orchestrator/agent/README.md)

### 2. Container Orchestration
Each user project runs in isolated containers with its own dev server.

- **Docker Mode**: Local development with Traefik routing
- **Kubernetes Mode**: Production with per-project namespaces

See: [Orchestration Documentation](orchestrator/orchestration/README.md)

### 3. S3 Sandwich Pattern
Project hibernation strategy for cost efficiency:

1. **Hydration**: Download project from S3 → PVC on pod start
2. **Runtime**: Fast local I/O
3. **Dehydration**: Upload to S3 on pod termination

See: [S3 Sandwich Documentation](infrastructure/kubernetes/s3-sandwich.md)

### 4. Deployment Modes
Tesslate supports multiple deployment targets:

- **Internal**: Docker/Kubernetes containers within Tesslate
- **External**: Vercel, Netlify, Cloudflare Pages

See: [Deployment Documentation](orchestrator/services/deployment-providers.md)

### 5. Real-Time Agent System
Distributed agent execution with progressive persistence and cross-pod visibility.

- **ARQ Workers**: Agents execute on dedicated worker pods, not inline in API requests
- **Redis Pub/Sub + Streams**: Real-time event streaming across pods
- **Progressive Persistence**: Each iteration saved as AgentStep row immediately
- **External API**: API key-based access for Slack, CLI, and webhook integrations

See: [Real-Time Agent Architecture](guides/real-time-agent-architecture.md)

## Repository Structure

```
tesslate-studio/
├── orchestrator/           # FastAPI backend
│   └── app/
│       ├── main.py        # Entry point
│       ├── routers/       # API endpoints
│       ├── services/      # Business logic
│       ├── worker.py      # ARQ worker for agent tasks
│       ├── agent/         # AI agent system
│       └── models.py      # Database models
│
├── app/                    # React frontend
│   └── src/
│       ├── pages/         # Route components
│       ├── components/    # UI components
│       ├── lib/           # API client
│       └── services/      # State management
│
├── k8s/                    # Kubernetes manifests
│   ├── base/              # Base manifests
│   └── overlays/          # Environment configs
│
├── docker-compose.yml      # Local development
└── docs/              # This documentation
```

## Getting Started

### For New Developers

1. **Set up Docker from scratch**: Follow [Docker Setup Guide](guides/docker-setup.md) — fastest way to get running
2. **Understand the architecture**: Read [Architecture Overview](architecture/README.md)
3. **Explore the codebase**: Use CLAUDE.md files for context
4. **Native development** (optional): See [Local Development Guide](guides/local-development.md) for running without Docker

### For Backend Development

1. Read [Orchestrator Overview](orchestrator/README.md)
2. Understand [Routers](orchestrator/routers/README.md) for API endpoints
3. Learn about [Services](orchestrator/services/README.md) for business logic

### For Frontend Development

1. Read [App Overview](app/README.md)
2. Explore [Components](app/components/README.md)
3. Understand [API Client](app/api/README.md)

### For DevOps

1. Read [Infrastructure Overview](infrastructure/README.md)
2. Follow [Minikube Setup](guides/minikube-setup.md) for local K8s
3. Review [AWS Deployment](guides/aws-deployment.md) for production

## CLAUDE.md Files

Each directory contains a `CLAUDE.md` file designed for AI agent context loading. These files form a **knowledge graph** with cross-references to help agents understand the codebase.

When working on a specific system:
1. Load the relevant `CLAUDE.md` file
2. Follow cross-references to related contexts
3. Use file references to navigate source code

## Diagrams

Visual architecture diagrams are in [architecture/diagrams/](architecture/diagrams/):

| Diagram | Description |
|---------|-------------|
| [high-level-architecture.mmd](architecture/diagrams/high-level-architecture.mmd) | Complete system overview |
| [request-flow.mmd](architecture/diagrams/request-flow.mmd) | API request lifecycle |
| [agent-execution.mmd](architecture/diagrams/agent-execution.mmd) | AI agent execution flow |
| [container-lifecycle.mmd](architecture/diagrams/container-lifecycle.mmd) | Project container management |
| [s3-sandwich.mmd](architecture/diagrams/s3-sandwich.mmd) | Hibernation pattern |
| [auth-flow.mmd](architecture/diagrams/auth-flow.mmd) | Authentication flows |
| [deployment-pipeline.mmd](architecture/diagrams/deployment-pipeline.mmd) | Build and deploy process |

## Contributing

When adding new documentation:

1. Follow the existing structure
2. Add CLAUDE.md files for new systems
3. Cross-reference related documentation
4. Include file references to source code
5. Keep diagrams updated

## Version

Documentation version: 2026.2
Last updated: February 2026
