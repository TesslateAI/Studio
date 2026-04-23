# OpenSail Guides

Practical how-to guides for developing, deploying, and extending OpenSail.

## Getting Started

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Docker Setup](docker-setup.md) | Set up OpenSail from scratch with Docker Compose | **Start here**. First-time setup, new developers |
| [Local Development](local-development.md) | Run backend/frontend natively (without Docker) | Faster iteration, debugging |
| [Minikube Setup](minikube-setup.md) | Deploy to local Kubernetes cluster | Testing K8s features locally |
| [AWS Deployment](aws-deployment.md) | Deploy to AWS EKS production | Production deployment |

## Development Workflows

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Image Update Workflow](image-update-workflow.md) | Build and deploy container images | After code changes, deploying updates |
| [Database Migrations](database-migrations.md) | Manage database schema changes | Adding/modifying database tables |
| [Environment Variables](environment-variables.md) | Full env var reference (all categories) | Configuring any environment |

## Extending the Platform

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Adding Routers](adding-routers.md) | Create new API endpoints | Building new backend features |
| [Adding Agent Tools](adding-agent-tools.md) | Create new AI agent tools | Extending agent capabilities |

## Operations

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Troubleshooting](troubleshooting.md) | Common issues and solutions | Debugging problems |
| [Safe Shutdown Procedure](safe-shutdown-procedure.md) | Graceful shutdown and upgrade process | System maintenance |

## Integration & Testing

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Stripe Testing](stripe-testing.md) | Stripe integration testing guide | Testing payment flows |
| [Stripe Integration Complete](stripe-integration-complete.md) | Full Stripe implementation summary | Understanding billing system |
| [Testing Reference](../testing/README.md) | Full test suite docs (pytest, vitest, Playwright, Go) | Writing, running, or triaging tests |
| [CI/CD Reference](../ci-cd/README.md) | GitHub Actions workflows, hooks, lint-staged | Adjusting pipelines or release process |

## Deep Dives & Architecture

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Agent System Architecture](agent-system-architecture.md) | Comprehensive agent system documentation | Understanding AI agents, skills, and tools |
| [Universal Project Setup](universal-project-setup.md) | `.tesslate/config.json` project configuration system | Understanding project config, container startup |
| [Edit Mode Implementation](edit-mode-implementation.md) | Three-mode edit system (Ask/Allow/Plan) | Understanding edit flow |
| [View-Scoped Tools](../orchestrator/agent/tools/view-scoped-tools.md) | View-specific agent tools | Extending view-based tools |
| [Enterprise Observability](enterprise-observability.md) | OpenTelemetry, structured logging, audit export plan | Adding tracing or compliance export |
| [Real-time Agent Architecture](real-time-agent-architecture.md) | Agent streaming, Redis pub/sub, WebSocket fan-out | Debugging live agent output |

## Specs

| Spec | Description |
|------|-------------|
| [App Manifest index](../specs/README.md) | Frozen Tesslate App manifest versions (2025-01, 2025-02) |

## Quick Reference

### Common Commands

```powershell
# Local Development (Docker). From-scratch setup
cp .env.example .env          # then edit .env with your keys
docker compose up --build -d  # build images and start
docker compose ps             # verify all services are healthy
docker compose logs -f        # watch logs

# Minikube
minikube start -p tesslate --driver=docker
kubectl apply -k k8s/overlays/minikube
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80

# AWS EKS
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>
kubectl apply -k k8s/overlays/aws
```

### Key Directories

```
orchestrator/           # FastAPI backend
  app/
    routers/           # API endpoints
    agent/tools/       # Agent tools
    services/          # Business logic
    models.py          # Database models
  alembic/             # Database migrations

app/                   # React frontend
  src/
    pages/             # Page components
    components/        # Reusable components

k8s/                   # Kubernetes manifests
  base/                # Shared base manifests
  overlays/
    minikube/          # Local development
    aws/               # Production (EKS)
```

### Environment Variables

See [environment-variables.md](environment-variables.md) for the complete reference. `.env.example` and `.env.prod.example` at the repo root document local / production defaults; `k8s/` overlays carry deployment-mode values.

## Contributing

When adding new guides:
1. Follow the existing format with clear step-by-step instructions
2. Include actual commands from the codebase
3. Reference specific files when appropriate
4. Add common issues and solutions
5. Update this README with the new guide
6. Use the OpenSail product name. Replace any "Tesslate Studio" references you encounter in the edited area
7. Avoid em dashes. Use colons, commas, semicolons, or periods
