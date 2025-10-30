"""
Seed initial marketplace bases.

Creates three featured fullstack bases:
1. Next.js 15 (Integrated fullstack)
2. Vite + React + FastAPI (Separated fullstack - Python)
3. Vite + React + Go (Separated fullstack - Go)

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_marketplace_bases.py

Docker:
  docker cp scripts/seed/seed_marketplace_bases.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_bases.py

Kubernetes:
  kubectl cp scripts/seed/seed_marketplace_bases.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_marketplace_bases.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.models import MarketplaceBase


async def seed_bases():
    """Seed initial marketplace bases."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("=== Seeding Marketplace Bases ===\n")

        bases_data = [
            MarketplaceBase(
                name="Next.js 15",
                slug="nextjs-15",
                description="Integrated fullstack with Next.js 15 and API routes",
                long_description="Modern Next.js 15 starter with App Router, React Server Components, API routes, TypeScript, and Tailwind CSS. All-in-one solution for rapid fullstack development with automatic image optimization and font loading.",
                git_repo_url="https://github.com/TesslateAI/Studio-NextJS-15-Base.git",
                default_branch="main",
                category="fullstack",
                icon="⚡",
                tags=["nextjs", "react", "typescript", "tailwind", "fullstack", "api-routes"],
                pricing_type="free",
                price=0,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=["App Router", "API Routes", "React Server Components", "TypeScript", "Tailwind CSS", "Hot Reload"],
                tech_stack=["Next.js 15", "React 19", "TypeScript", "Tailwind CSS"],
                is_featured=True,
                is_active=True
            ),
            MarketplaceBase(
                name="Vite + React + FastAPI",
                slug="vite-react-fastapi",
                description="Separated fullstack with Vite React frontend and FastAPI Python backend",
                long_description="Full-stack template with explicit separation: Vite + React for the frontend and FastAPI for the backend. Includes CORS setup, hot reload for both servers, PostgreSQL integration, and example CRUD API endpoints. Perfect for data science and ML applications.",
                git_repo_url="https://github.com/TesslateAI/Studio-Vite-React-FastAPI-Base.git",
                default_branch="main",
                category="fullstack",
                icon="🐍",
                tags=["vite", "react", "fastapi", "python", "fullstack", "postgresql"],
                pricing_type="free",
                price=0,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=["Vite Frontend", "FastAPI Backend", "Dual Hot Reload", "CORS Configured", "PostgreSQL Ready", "Example CRUD API"],
                tech_stack=["Vite", "React", "FastAPI", "Python", "PostgreSQL"],
                is_featured=True,
                is_active=True
            ),
            MarketplaceBase(
                name="Vite + React + Go",
                slug="vite-react-go",
                description="High-performance fullstack with Vite React frontend and Go backend",
                long_description="Performance-focused fullstack template with Vite + React for the frontend and Go with Chi router for the backend. Includes Air for hot reloading, CORS middleware, example REST endpoints, and WebSocket support. Ideal for real-time applications and microservices.",
                git_repo_url="https://github.com/TesslateAI/Studio-Vite-React-Go-Base.git",
                default_branch="main",
                category="fullstack",
                icon="🔷",
                tags=["vite", "react", "go", "golang", "fullstack", "chi-router", "websocket"],
                pricing_type="free",
                price=0,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=["Vite Frontend", "Go Backend", "Air Hot Reload", "Chi Router", "CORS Middleware", "WebSocket Support", "REST API"],
                tech_stack=["Vite", "React", "Go", "Chi Router", "Air"],
                is_featured=True,
                is_active=True
            )
        ]

        created_count = 0
        skipped_count = 0

        for base_data in bases_data:
            # Check if base already exists by slug
            existing = await db.execute(
                select(MarketplaceBase).where(MarketplaceBase.slug == base_data.slug)
            )
            if existing.scalars().first():
                print(f"⏭️  Base '{base_data.name}' already exists, skipping")
                skipped_count += 1
                continue

            db.add(base_data)
            print(f"✓ Adding base: {base_data.name}")
            created_count += 1

        if created_count > 0:
            await db.commit()
            print(f"\n=== Successfully seeded {created_count} marketplace bases! ===")

        if skipped_count > 0:
            print(f"=== Skipped {skipped_count} existing bases ===")

        print()


if __name__ == "__main__":
    asyncio.run(seed_bases())
