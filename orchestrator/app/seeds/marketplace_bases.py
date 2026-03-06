"""
Seed marketplace bases.

Creates the 4 official project templates (Next.js 16,
Vite+React+FastAPI, Vite+React+Go, Expo).

Can be run standalone or called from the startup seeder.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceBase

logger = logging.getLogger(__name__)

DEFAULT_BASES = [
    {
        "name": "Next.js 16",
        "slug": "nextjs-16",
        "description": "Integrated fullstack with Next.js 16, React Compiler, Turbopack, and instant startup",
        "long_description": "Production-ready Next.js 16.1 starter with App Router, React 19.2, the stable React Compiler, Turbopack, API routes, TypeScript 5.9, and Tailwind CSS v4.2. Includes View Transitions, Cache Components, and Server Actions. Pre-baked dependencies for instant startup.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-NextJS-16-Base.git",
        "default_branch": "main",
        "category": "fullstack",
        "icon": "\u26a1",
        "tags": [
            "nextjs",
            "react",
            "typescript",
            "tailwind",
            "fullstack",
            "api-routes",
            "turbopack",
            "react-compiler",
        ],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": [
            "App Router",
            "API Routes",
            "Turbopack",
            "React 19.2",
            "React Compiler",
            "TypeScript 5.9",
            "Tailwind CSS v4.2",
            "View Transitions",
            "Cache Components",
            "Instant Startup",
        ],
        "tech_stack": [
            "Next.js 16.1",
            "React 19.2",
            "TypeScript 5.9",
            "Tailwind CSS v4.2",
            "Turbopack",
        ],
        "is_featured": True,
        "is_active": True,
    },
    {
        "name": "Vite + React + FastAPI",
        "slug": "vite-react-fastapi",
        "description": "Separated fullstack with Vite React frontend and FastAPI Python backend",
        "long_description": "Full-stack template with explicit separation: Vite + React for the frontend and FastAPI for the backend. Includes CORS setup, hot reload for both servers, PostgreSQL integration, and example CRUD API endpoints. Perfect for data science and ML applications.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-Vite-React-FastAPI-Base.git",
        "default_branch": "main",
        "category": "fullstack",
        "icon": "\U0001f40d",
        "tags": ["vite", "react", "fastapi", "python", "fullstack", "postgresql"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": [
            "Vite Frontend",
            "FastAPI Backend",
            "Dual Hot Reload",
            "CORS Configured",
            "PostgreSQL Ready",
            "Example CRUD API",
        ],
        "tech_stack": ["Vite", "React", "FastAPI", "Python", "PostgreSQL"],
        "is_featured": True,
        "is_active": True,
    },
    {
        "name": "Vite + React + Go",
        "slug": "vite-react-go",
        "description": "High-performance fullstack with Vite React frontend and Go backend",
        "long_description": "Performance-focused fullstack template with Vite + React for the frontend and Go with Chi router for the backend. Includes Air for hot reloading, CORS middleware, example REST endpoints, and WebSocket support. Ideal for real-time applications and microservices.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-Vite-React-Go-Base.git",
        "default_branch": "main",
        "category": "fullstack",
        "icon": "\U0001f537",
        "tags": ["vite", "react", "go", "golang", "fullstack", "chi-router", "websocket"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": [
            "Vite Frontend",
            "Go Backend",
            "Air Hot Reload",
            "Chi Router",
            "CORS Middleware",
            "WebSocket Support",
            "REST API",
        ],
        "tech_stack": ["Vite", "React", "Go", "Chi Router", "Air"],
        "is_featured": True,
        "is_active": True,
    },
    {
        "name": "Expo",
        "slug": "expo-default",
        "description": "Cross-platform mobile app with Expo Router and React Native",
        "long_description": "Modern Expo starter template with file-based routing, React Native 0.81, React 19, and multi-platform support. Perfect for building iOS, Android, and web applications from a single codebase with hot reload and TypeScript. Features Expo Router for intuitive navigation and Metro bundler for optimized performance.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-Expo-Base.git",
        "default_branch": "main",
        "category": "mobile",
        "icon": "\U0001f4f1",
        "tags": ["expo", "react-native", "mobile", "typescript", "ios", "android", "web", "metro"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": [
            "File-based Routing",
            "Expo Router",
            "Multi-platform (iOS/Android/Web)",
            "Hot Reload",
            "TypeScript",
            "React Native 0.81",
            "Metro Bundler",
            "React 19",
        ],
        "tech_stack": ["Expo SDK 54", "React Native 0.81", "React 19", "TypeScript", "Metro"],
        "is_featured": True,
        "is_active": True,
    },
]


async def seed_marketplace_bases(db: AsyncSession) -> int:
    """Seed marketplace bases. Upserts by slug.

    Returns:
        Number of newly created bases.
    """
    created = 0
    updated = 0

    for base_data in DEFAULT_BASES:
        result = await db.execute(
            select(MarketplaceBase).where(MarketplaceBase.slug == base_data["slug"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in base_data.items():
                if key != "slug":
                    setattr(existing, key, value)
            updated += 1
            logger.info("Updated base: %s", base_data["slug"])
        else:
            base = MarketplaceBase(**base_data)
            db.add(base)
            created += 1
            logger.info("Created base: %s", base_data["name"])

    await db.commit()

    logger.info(
        "Marketplace bases: %d created, %d updated", created, updated
    )
    return created
