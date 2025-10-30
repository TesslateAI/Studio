"""
Automatic database seeding for marketplace content.

This module provides consolidated seeding functionality that runs automatically
on application startup. All seeding operations are idempotent and safe to run
multiple times.

Seeded Content:
- Marketplace Agents (4 agents)
- Marketplace Bases (3 project templates)
- Open Source Agents (6 customizable agents)
"""

import asyncio
import logging
import time
import sys
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .models import MarketplaceAgent, MarketplaceBase, User, UserPurchasedAgent
from .database import engine

logger = logging.getLogger(__name__)

# Add scripts directory to path for imports
scripts_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)


async def seed_marketplace_agents(session: AsyncSession) -> dict:
    """
    Seed marketplace agents (Stream Builder, Tesslate Agent, etc.).

    Returns:
        dict: {"created": int, "existing": int, "total": int}
    """
    # Import the actual seed data from the existing script
    from seed.seed_marketplace_agents import DEFAULT_AGENTS

    created_count = 0
    existing_count = 0

    for agent_data in DEFAULT_AGENTS:
        # Check if agent exists by slug
        existing = await session.scalar(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_data["slug"])
        )

        if existing:
            existing_count += 1
            continue

        # Create new agent
        agent = MarketplaceAgent(**agent_data)
        session.add(agent)
        created_count += 1
        logger.debug(f"Creating agent: {agent_data['name']}")

    if created_count > 0:
        await session.commit()

        # Auto-add Stream Builder to all existing users
        stream_builder = await session.scalar(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == "stream-builder")
        )

        if stream_builder:
            users = await session.scalars(select(User))
            for user in users:
                # Check if user already has it
                has_agent = await session.scalar(
                    select(UserPurchasedAgent).where(
                        UserPurchasedAgent.user_id == user.id,
                        UserPurchasedAgent.agent_id == stream_builder.id
                    )
                )

                if not has_agent:
                    purchase = UserPurchasedAgent(
                        user_id=user.id,
                        agent_id=stream_builder.id,
                        purchase_type="free"
                    )
                    session.add(purchase)
                    logger.debug(f"Auto-adding Stream Builder to user: {user.email}")

            await session.commit()

    return {
        "created": created_count,
        "existing": existing_count,
        "total": len(DEFAULT_AGENTS)
    }


async def seed_marketplace_bases(session: AsyncSession) -> dict:
    """
    Seed marketplace bases (Next.js 15, Vite+React+FastAPI, Vite+React+Go).

    Returns:
        dict: {"created": int, "existing": int, "total": int}
    """
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
    existing_count = 0

    for base_data in bases_data:
        # Check if base exists by slug
        existing = await session.scalar(
            select(MarketplaceBase).where(MarketplaceBase.slug == base_data.slug)
        )

        if existing:
            existing_count += 1
            continue

        session.add(base_data)
        created_count += 1
        logger.debug(f"Creating base: {base_data.name}")

    if created_count > 0:
        await session.commit()

    return {
        "created": created_count,
        "existing": existing_count,
        "total": len(bases_data)
    }


async def seed_opensource_agents(session: AsyncSession) -> dict:
    """
    Seed open source agents (Code Analyzer, Documentation Writer, etc.).

    Returns:
        dict: {"created": int, "existing": int, "total": int}
    """
    # Import the actual seed data from the existing script
    from seed.seed_opensource_agents import OPENSOURCE_AGENTS

    created_count = 0
    existing_count = 0

    for agent_data in OPENSOURCE_AGENTS:
        # Check if agent exists by slug
        existing = await session.scalar(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_data["slug"])
        )

        if existing:
            existing_count += 1
            continue

        # Create new agent
        agent = MarketplaceAgent(**agent_data)
        session.add(agent)
        created_count += 1
        logger.debug(f"Creating open source agent: {agent_data['name']}")

    if created_count > 0:
        await session.commit()

    return {
        "created": created_count,
        "existing": existing_count,
        "total": len(OPENSOURCE_AGENTS)
    }


async def run_all_seeds() -> dict:
    """
    Run all seeding scripts in the correct order.
    Safe to call multiple times (idempotent).

    Returns:
        dict: Summary of seeding results
        {
            "marketplace_agents": {"created": 4, "existing": 0, "total": 4},
            "marketplace_bases": {"created": 3, "existing": 0, "total": 3},
            "opensource_agents": {"created": 6, "existing": 0, "total": 6},
            "total_created": 13,
            "total_existing": 0,
            "duration_ms": 234
        }
    """
    start_time = time.time()

    logger.info("Starting automatic database seeding...")

    # Create async session
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    results = {}
    total_created = 0
    total_existing = 0

    async with AsyncSessionLocal() as session:
        try:
            # Seed marketplace agents first
            logger.info("Seeding marketplace agents...")
            agents_result = await seed_marketplace_agents(session)
            results["marketplace_agents"] = agents_result
            total_created += agents_result["created"]
            total_existing += agents_result["existing"]

            # Seed marketplace bases
            logger.info("Seeding marketplace bases...")
            bases_result = await seed_marketplace_bases(session)
            results["marketplace_bases"] = bases_result
            total_created += bases_result["created"]
            total_existing += bases_result["existing"]

            # Seed open source agents
            logger.info("Seeding open source agents...")
            oss_result = await seed_opensource_agents(session)
            results["opensource_agents"] = oss_result
            total_created += oss_result["created"]
            total_existing += oss_result["existing"]

        except Exception as e:
            logger.error(f"Error during seeding: {e}", exc_info=True)
            raise

    duration_ms = int((time.time() - start_time) * 1000)

    results["total_created"] = total_created
    results["total_existing"] = total_existing
    results["duration_ms"] = duration_ms

    if total_created > 0:
        logger.info(
            f"Seeding complete! Created {total_created} items "
            f"({results['marketplace_agents']['created']} agents, "
            f"{results['marketplace_bases']['created']} bases, "
            f"{results['opensource_agents']['created']} OSS agents) "
            f"in {duration_ms}ms"
        )
    else:
        logger.info(f"Database already seeded ({total_existing} existing items), skipping")

    return results


async def check_seed_status() -> dict:
    """
    Check what has been seeded without making changes.

    Returns:
        dict: Status of each category
        {
            "marketplace_agents": {"count": 4, "seeded": True},
            "marketplace_bases": {"count": 3, "seeded": True},
            "total_items": 7
        }
    """
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        agents_count = await session.scalar(
            select(MarketplaceAgent).where(
                MarketplaceAgent.slug.in_([
                    "stream-builder", "fullstack-agent", "react-component-builder", "api-integration-agent"
                ])
            ).count()
        )

        bases_count = await session.scalar(
            select(MarketplaceBase).where(
                MarketplaceBase.slug.in_([
                    "nextjs-15", "vite-react-fastapi", "vite-react-go"
                ])
            ).count()
        )

        return {
            "marketplace_agents": {
                "count": agents_count,
                "seeded": agents_count >= 4
            },
            "marketplace_bases": {
                "count": bases_count,
                "seeded": bases_count >= 3
            },
            "total_items": agents_count + bases_count
        }
