"""
Seed data for workflow templates.

Run this to populate the database with initial workflow templates.
Usage: python -m app.seeds.workflow_templates
"""

import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Workflow template definitions
WORKFLOW_TEMPLATES = [
    {
        "name": "Next.js + Supabase Starter",
        "slug": "nextjs-supabase-starter",
        "description": "Full-stack starter with Next.js 14, Supabase (database, auth, storage), and Tailwind CSS",
        "long_description": """
A production-ready starter template combining Next.js 14 with Supabase for a complete full-stack experience.

**Includes:**
- Next.js 14 with App Router
- Supabase for database, authentication, and file storage
- Tailwind CSS for styling
- TypeScript support
- Pre-configured environment variables

**Perfect for:**
- SaaS applications
- Web apps with user authentication
- Projects needing real-time features
        """,
        "icon": "⚡",
        "category": "fullstack",
        "tags": ["nextjs", "supabase", "typescript", "tailwind", "auth"],
        "template_definition": {
            "nodes": [
                {
                    "template_id": "frontend",
                    "type": "base",
                    "base_slug": "nextjs",
                    "name": "Frontend",
                    "position": {"x": 100, "y": 150}
                },
                {
                    "template_id": "database",
                    "type": "service",
                    "service_slug": "supabase",
                    "name": "Supabase",
                    "position": {"x": 450, "y": 150}
                }
            ],
            "edges": [
                {
                    "source": "frontend",
                    "target": "database",
                    "connector_type": "env_injection",
                    "config": {
                        "env_mapping": {
                            "NEXT_PUBLIC_SUPABASE_URL": "SUPABASE_URL",
                            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "SUPABASE_ANON_KEY",
                            "SUPABASE_SERVICE_ROLE_KEY": "SUPABASE_SERVICE_ROLE_KEY"
                        }
                    }
                }
            ],
            "required_credentials": ["supabase"]
        },
        "required_credentials": ["supabase"],
        "pricing_type": "free",
        "is_featured": True
    },
    {
        "name": "React + FastAPI + PostgreSQL",
        "slug": "react-fastapi-postgres",
        "description": "Full-stack app with React frontend, FastAPI backend, and PostgreSQL database",
        "long_description": """
A robust full-stack template with clear separation of concerns.

**Includes:**
- React with Vite for fast development
- FastAPI for high-performance Python backend
- PostgreSQL for reliable data storage
- Docker-based development environment

**Perfect for:**
- REST API applications
- Data-driven web apps
- Python developers building full-stack apps
        """,
        "icon": "🐍",
        "category": "fullstack",
        "tags": ["react", "fastapi", "python", "postgresql", "vite"],
        "template_definition": {
            "nodes": [
                {
                    "template_id": "frontend",
                    "type": "base",
                    "base_slug": "react-vite",
                    "name": "Frontend",
                    "position": {"x": 100, "y": 100}
                },
                {
                    "template_id": "backend",
                    "type": "base",
                    "base_slug": "fastapi",
                    "name": "API",
                    "position": {"x": 100, "y": 300}
                },
                {
                    "template_id": "database",
                    "type": "service",
                    "service_slug": "postgres",
                    "name": "PostgreSQL",
                    "position": {"x": 450, "y": 300}
                }
            ],
            "edges": [
                {
                    "source": "frontend",
                    "target": "backend",
                    "connector_type": "http_api",
                    "config": {
                        "env_mapping": {
                            "VITE_API_URL": "http://{container_name}:{port}"
                        }
                    }
                },
                {
                    "source": "backend",
                    "target": "database",
                    "connector_type": "database",
                    "config": {
                        "env_mapping": {
                            "DATABASE_URL": "DATABASE_URL"
                        }
                    }
                }
            ],
            "required_credentials": []
        },
        "required_credentials": [],
        "pricing_type": "free",
        "is_featured": True
    },
    {
        "name": "REST API + PostgreSQL + Redis",
        "slug": "rest-api-postgres-redis",
        "description": "Production-ready REST API with FastAPI, PostgreSQL for data, and Redis for caching",
        "long_description": """
A scalable backend template with caching and database layers.

**Includes:**
- FastAPI with async support
- PostgreSQL for persistent storage
- Redis for caching and sessions
- Health checks and production configs

**Perfect for:**
- Microservices
- High-performance APIs
- Apps requiring caching
        """,
        "icon": "🚀",
        "category": "backend",
        "tags": ["fastapi", "postgresql", "redis", "api", "caching"],
        "template_definition": {
            "nodes": [
                {
                    "template_id": "api",
                    "type": "base",
                    "base_slug": "fastapi",
                    "name": "API Server",
                    "position": {"x": 100, "y": 200}
                },
                {
                    "template_id": "database",
                    "type": "service",
                    "service_slug": "postgres",
                    "name": "PostgreSQL",
                    "position": {"x": 400, "y": 100}
                },
                {
                    "template_id": "cache",
                    "type": "service",
                    "service_slug": "redis",
                    "name": "Redis Cache",
                    "position": {"x": 400, "y": 300}
                }
            ],
            "edges": [
                {
                    "source": "api",
                    "target": "database",
                    "connector_type": "database",
                    "config": {
                        "env_mapping": {
                            "DATABASE_URL": "DATABASE_URL"
                        }
                    }
                },
                {
                    "source": "api",
                    "target": "cache",
                    "connector_type": "cache",
                    "config": {
                        "env_mapping": {
                            "REDIS_URL": "REDIS_URL"
                        }
                    }
                }
            ],
            "required_credentials": []
        },
        "required_credentials": [],
        "pricing_type": "free",
        "is_featured": False
    },
    {
        "name": "AI Chat Backend",
        "slug": "ai-chat-backend",
        "description": "AI-powered chat backend with OpenAI, PostgreSQL for history, and Redis for sessions",
        "long_description": """
Build AI chat applications with this ready-to-use backend.

**Includes:**
- FastAPI backend with streaming support
- OpenAI integration for GPT models
- PostgreSQL for chat history
- Redis for session management

**Perfect for:**
- ChatGPT-like applications
- AI assistants
- Conversational interfaces
        """,
        "icon": "🤖",
        "category": "ai-app",
        "tags": ["openai", "fastapi", "postgresql", "redis", "ai", "chat"],
        "template_definition": {
            "nodes": [
                {
                    "template_id": "api",
                    "type": "base",
                    "base_slug": "fastapi",
                    "name": "Chat API",
                    "position": {"x": 250, "y": 100}
                },
                {
                    "template_id": "ai",
                    "type": "service",
                    "service_slug": "openai",
                    "name": "OpenAI",
                    "position": {"x": 500, "y": 100}
                },
                {
                    "template_id": "database",
                    "type": "service",
                    "service_slug": "postgres",
                    "name": "Chat History",
                    "position": {"x": 100, "y": 300}
                },
                {
                    "template_id": "cache",
                    "type": "service",
                    "service_slug": "redis",
                    "name": "Sessions",
                    "position": {"x": 400, "y": 300}
                }
            ],
            "edges": [
                {
                    "source": "api",
                    "target": "ai",
                    "connector_type": "env_injection",
                    "config": {
                        "env_mapping": {
                            "OPENAI_API_KEY": "OPENAI_API_KEY"
                        }
                    }
                },
                {
                    "source": "api",
                    "target": "database",
                    "connector_type": "database",
                    "config": {
                        "env_mapping": {
                            "DATABASE_URL": "DATABASE_URL"
                        }
                    }
                },
                {
                    "source": "api",
                    "target": "cache",
                    "connector_type": "cache",
                    "config": {
                        "env_mapping": {
                            "REDIS_URL": "REDIS_URL"
                        }
                    }
                }
            ],
            "required_credentials": ["openai"]
        },
        "required_credentials": ["openai"],
        "pricing_type": "free",
        "is_featured": True
    },
    {
        "name": "SaaS Starter with Payments",
        "slug": "saas-starter-payments",
        "description": "Complete SaaS template with Next.js, Supabase auth, Stripe payments, and Resend email",
        "long_description": """
Launch your SaaS product with all the essentials built-in.

**Includes:**
- Next.js 14 for the frontend
- Supabase for auth and database
- Stripe for subscriptions and payments
- Resend for transactional emails

**Perfect for:**
- SaaS products
- Subscription-based apps
- Products needing payment integration
        """,
        "icon": "💰",
        "category": "fullstack",
        "tags": ["nextjs", "supabase", "stripe", "resend", "saas", "payments"],
        "template_definition": {
            "nodes": [
                {
                    "template_id": "frontend",
                    "type": "base",
                    "base_slug": "nextjs",
                    "name": "Web App",
                    "position": {"x": 50, "y": 200}
                },
                {
                    "template_id": "database",
                    "type": "service",
                    "service_slug": "supabase",
                    "name": "Supabase",
                    "position": {"x": 350, "y": 100}
                },
                {
                    "template_id": "payments",
                    "type": "service",
                    "service_slug": "stripe",
                    "name": "Stripe",
                    "position": {"x": 350, "y": 300}
                },
                {
                    "template_id": "email",
                    "type": "service",
                    "service_slug": "resend",
                    "name": "Resend",
                    "position": {"x": 600, "y": 200}
                }
            ],
            "edges": [
                {
                    "source": "frontend",
                    "target": "database",
                    "connector_type": "env_injection",
                    "config": {
                        "env_mapping": {
                            "NEXT_PUBLIC_SUPABASE_URL": "SUPABASE_URL",
                            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "SUPABASE_ANON_KEY"
                        }
                    }
                },
                {
                    "source": "frontend",
                    "target": "payments",
                    "connector_type": "env_injection",
                    "config": {
                        "env_mapping": {
                            "STRIPE_SECRET_KEY": "STRIPE_SECRET_KEY",
                            "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY": "STRIPE_PUBLISHABLE_KEY"
                        }
                    }
                },
                {
                    "source": "frontend",
                    "target": "email",
                    "connector_type": "env_injection",
                    "config": {
                        "env_mapping": {
                            "RESEND_API_KEY": "RESEND_API_KEY"
                        }
                    }
                }
            ],
            "required_credentials": ["supabase", "stripe", "resend"]
        },
        "required_credentials": ["supabase", "stripe", "resend"],
        "pricing_type": "free",
        "is_featured": True
    },
    {
        "name": "Monitoring Stack",
        "slug": "monitoring-stack",
        "description": "Prometheus metrics collection with Grafana dashboards for observability",
        "long_description": """
Add observability to your infrastructure with this monitoring stack.

**Includes:**
- Prometheus for metrics collection
- Grafana for visualization
- Pre-configured dashboards

**Perfect for:**
- Production monitoring
- Performance analysis
- DevOps teams
        """,
        "icon": "📊",
        "category": "devops",
        "tags": ["prometheus", "grafana", "monitoring", "devops", "metrics"],
        "template_definition": {
            "nodes": [
                {
                    "template_id": "prometheus",
                    "type": "service",
                    "service_slug": "prometheus",
                    "name": "Prometheus",
                    "position": {"x": 100, "y": 200}
                },
                {
                    "template_id": "grafana",
                    "type": "service",
                    "service_slug": "grafana",
                    "name": "Grafana",
                    "position": {"x": 400, "y": 200}
                }
            ],
            "edges": [
                {
                    "source": "grafana",
                    "target": "prometheus",
                    "connector_type": "http_api",
                    "config": {
                        "env_mapping": {
                            "PROMETHEUS_URL": "http://{container_name}:{port}"
                        }
                    }
                }
            ],
            "required_credentials": []
        },
        "required_credentials": [],
        "pricing_type": "free",
        "is_featured": False
    }
]


async def seed_workflow_templates():
    """Seed workflow templates into the database."""
    from ..database import AsyncSessionLocal
    from ..models import WorkflowTemplate

    async with AsyncSessionLocal() as db:
        for template_data in WORKFLOW_TEMPLATES:
            # Check if already exists
            result = await db.execute(
                select(WorkflowTemplate).where(WorkflowTemplate.slug == template_data["slug"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"Workflow '{template_data['slug']}' already exists, skipping...")
                continue

            # Create new workflow
            workflow = WorkflowTemplate(
                id=uuid.uuid4(),
                name=template_data["name"],
                slug=template_data["slug"],
                description=template_data["description"],
                long_description=template_data.get("long_description"),
                icon=template_data["icon"],
                category=template_data["category"],
                tags=template_data.get("tags"),
                template_definition=template_data["template_definition"],
                required_credentials=template_data.get("required_credentials"),
                pricing_type=template_data.get("pricing_type", "free"),
                price=template_data.get("price", 0),
                is_featured=template_data.get("is_featured", False),
                is_active=True
            )
            db.add(workflow)
            print(f"Created workflow: {template_data['name']}")

        await db.commit()
        print(f"\nSeeded {len(WORKFLOW_TEMPLATES)} workflow templates!")


if __name__ == "__main__":
    asyncio.run(seed_workflow_templates())
