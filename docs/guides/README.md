# Tesslate Studio Guides

Practical how-to guides for developing, deploying, and extending Tesslate Studio.

## Getting Started

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Docker Setup](docker-setup.md) | Set up Tesslate Studio from scratch with Docker Compose | **Start here** — first-time setup, new developers |
| [Local Development](local-development.md) | Run backend/frontend natively (without Docker) | Faster iteration, debugging |
| [Minikube Setup](minikube-setup.md) | Deploy to local Kubernetes cluster | Testing K8s features locally |
| [AWS Deployment](aws-deployment.md) | Deploy to AWS EKS production | Production deployment |

## Development Workflows

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Image Update Workflow](image-update-workflow.md) | Build and deploy container images | After code changes, deploying updates |
| [Database Migrations](database-migrations.md) | Manage database schema changes | Adding/modifying database tables |

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

## Deep Dives & Architecture

| Guide | Description | When to Use |
|-------|-------------|-------------|
| [Agent System Architecture](agent-system-architecture.md) | Comprehensive agent system documentation | Understanding AI agents, skills, and tools |
| [Universal Project Setup](universal-project-setup.md) | `.tesslate/config.json` project configuration system | Understanding project config, container startup |
| [Edit Mode Implementation](edit-mode-implementation.md) | Three-mode edit system (Ask/Allow/Plan) | Understanding edit flow |
| [View-Scoped Tools](../orchestrator/agent/tools/view-scoped-tools.md) | View-specific agent tools | Extending view-based tools |

## Quick Reference

### Common Commands

```powershell
# Local Development (Docker) — from-scratch setup
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

See `.env.example` files in the root directory and `k8s/` folder for required environment variables.

## Contributing

When adding new guides:
1. Follow the existing format with clear step-by-step instructions
2. Include actual commands from the codebase
3. Reference specific files when appropriate
4. Add common issues and solutions
5. Update this README with the new guide
