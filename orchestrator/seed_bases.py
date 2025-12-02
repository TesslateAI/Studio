"""
Seed initial marketplace bases - Docker compatible version
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import get_settings
from app.models import MarketplaceBase


async def seed_bases():
    """Seed initial marketplace bases."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("=== Seeding Marketplace Bases ===\n")

        bases = [
            # === Fullstack Bases (Combined Frontend + Backend) ===
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
            ),
            # === Standalone Frontend Bases ===
            MarketplaceBase(
                name="Next.js",
                slug="nextjs",
                description="Modern React framework with server-side rendering",
                long_description="Next.js starter with App Router, TypeScript, and Tailwind CSS. Perfect for building frontend applications that can connect to any backend service.",
                git_repo_url="https://github.com/TesslateAI/Studio-NextJS-15-Base.git",
                default_branch="main",
                category="frontend",
                icon="⚡",
                tags=["nextjs", "react", "typescript", "tailwind", "frontend"],
                pricing_type="free",
                price=0,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=["App Router", "TypeScript", "Tailwind CSS", "Hot Reload"],
                tech_stack=["Next.js 15", "React 19", "TypeScript", "Tailwind CSS"],
                is_featured=False,
                is_active=True
            ),
            MarketplaceBase(
                name="React + Vite",
                slug="react-vite",
                description="Lightning-fast React development with Vite",
                long_description="Modern React starter powered by Vite for instant HMR and optimized builds. Includes TypeScript and Tailwind CSS pre-configured.",
                git_repo_url="https://github.com/TesslateAI/Studio-React-Vite-Base.git",
                default_branch="main",
                category="frontend",
                icon="⚛️",
                tags=["react", "vite", "typescript", "tailwind", "frontend"],
                pricing_type="free",
                price=0,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=["Vite Build", "React 19", "TypeScript", "Tailwind CSS", "Hot Module Replacement"],
                tech_stack=["Vite", "React 19", "TypeScript", "Tailwind CSS"],
                is_featured=False,
                is_active=True
            ),
            # === Standalone Backend Bases ===
            MarketplaceBase(
                name="FastAPI",
                slug="fastapi",
                description="High-performance Python API framework",
                long_description="FastAPI backend with automatic OpenAPI docs, async support, and Pydantic validation. Ready for production with health checks and logging.",
                git_repo_url="https://github.com/TesslateAI/Studio-FastAPI-Base.git",
                default_branch="main",
                category="backend",
                icon="🐍",
                tags=["fastapi", "python", "api", "backend", "async"],
                pricing_type="free",
                price=0,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=["OpenAPI Docs", "Async Support", "Pydantic Validation", "Hot Reload", "Health Checks"],
                tech_stack=["FastAPI", "Python", "Uvicorn", "Pydantic"],
                is_featured=False,
                is_active=True
            ),
        ]

        added_count = 0
        for base in bases:
            # Check if this base already exists by slug
            existing = await db.execute(
                select(MarketplaceBase).where(MarketplaceBase.slug == base.slug)
            )
            if existing.scalar_one_or_none():
                print(f"⚠️  Base '{base.slug}' already exists, skipping...")
                continue

            db.add(base)
            print(f"✓ Adding base: {base.name}")
            added_count += 1

        await db.commit()
        if added_count > 0:
            print(f"\n=== Successfully seeded {added_count} new marketplace bases! ===\n")
        else:
            print("\n=== No new bases to seed (all already exist) ===\n")


if __name__ == "__main__":
    asyncio.run(seed_bases())
