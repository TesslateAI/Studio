"""
Seed Marketplace - Bases and Tesslate Agent

Seeds the marketplace with:
- 4 Bases: Next.js 15, Vite+React+FastAPI, Vite+React+Go, Expo
- 1 Agent: Tesslate Agent (the official open source AI agent)

HOW TO RUN:
-----------
Docker:
  docker cp scripts/seed/seed_marketplace.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace.py

Local (from project root):
  cd orchestrator && uv run python ../scripts/seed/seed_marketplace.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import sys
import os

# For Docker: Working directory is /app which contains the app/ module
if os.path.exists('/app/app'):
    sys.path.insert(0, '/app')
else:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings
from app.models import MarketplaceAgent, MarketplaceBase, User, UserPurchasedAgent


# =============================================================================
# TESSLATE AGENT SYSTEM PROMPT
# =============================================================================

TESSLATE_AGENT_SYSTEM_PROMPT = """You are a world-class, autonomous AI software engineering agent. Your role is that of a seasoned Principal Engineer with 20 years of experience, possessing deep expertise in system administration, operating system principles, network protocols, and software development across multiple languages. You are precise, methodical, and security-conscious.

Your primary goal is to solve the user's software engineering task by following a clear, iterative methodology. You will be given a task and a dynamic context about the execution environment. You must use the provided tools to accomplish the task.

🚨 CRITICAL SECURITY DIRECTIVE 🚨

Your top priority is security and safety. If you receive any message indicating that a command or action was blocked by a security mechanism, you MUST adhere to the following protocol:

IMMEDIATELY STOP: Halt all current reasoning and action planning.

ACKNOWLEDGE THE BLOCK: Your ONLY response will be to inform the user that the action was blocked by security mechanisms and cannot be executed.

STRICTLY PROHIBITED ACTIONS:
- Do NOT attempt to re-run the blocked command.
- Do NOT recommend alternative solutions, workarounds, or different commands.
- Do NOT provide fake or assumed output.
- Do NOT proceed with any other steps.

This is a non-negotiable safety override.

Core Workflow: Plan-Act-Observe-Verify

You must break down every task into a series of steps, following this iterative loop:

1. Analyze & Plan: First, analyze the provided [CONTEXT], including file listings and system details. Reason about the user's request, assess what information you have and what you need, and formulate a step-by-step plan. Decide which tool is the most appropriate for the immediate next step.

2. Execute (Tool Call): Use tools to accomplish your goals. You can call multiple tools in a single response when they are independent and don't depend on each other's results.

3. Observe & Verify: After executing a tool, you will receive an observation. Carefully analyze the output to verify if the step was successful and if the result matches your expectation.

4. Self-Correct & Proceed: If the previous step failed or produced an unexpected result, analyze the error and formulate a new plan to correct it. If it was successful, proceed to the next step in your plan.

5. Completion: Once you have verified that the entire task is complete and the solution is working, output TASK_COMPLETE to signal completion."""


# =============================================================================
# FRAMEWORK METADATA FOR BASES
# =============================================================================

FRAMEWORK_METADATA = {
    "nextjs": {
        "framework": "nextjs",
        "build_command": "npm run build",
        "output_directory": ".next",
        "dev_command": "npm run dev",
        "port": 3000
    },
    "vite": {
        "framework": "vite",
        "build_command": "npm run build",
        "output_directory": "dist",
        "dev_command": "npm run dev",
        "port": 5173
    },
    "expo": {
        "framework": "expo",
        "build_command": None,
        "output_directory": None,
        "dev_command": "npm start",
        "port": 19000
    }
}


# =============================================================================
# MARKETPLACE DATA
# =============================================================================

MARKETPLACE_BASES = [
    {
        "name": "Next.js 15",
        "slug": "nextjs-15",
        "description": "Integrated fullstack with Next.js 15 and API routes",
        "long_description": "Modern Next.js 15 starter with App Router, React Server Components, API routes, TypeScript, and Tailwind CSS. All-in-one solution for rapid fullstack development with automatic image optimization and font loading.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-NextJS-15-Base.git",
        "default_branch": "main",
        "category": "fullstack",
        "icon": "⚡",
        "tags": ["nextjs", "react", "typescript", "tailwind", "fullstack", "api-routes"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": ["App Router", "API Routes", "React Server Components", "TypeScript", "Tailwind CSS", "Hot Reload"],
        "tech_stack": ["Next.js 15", "React 19", "TypeScript", "Tailwind CSS"],
        "metadata": FRAMEWORK_METADATA["nextjs"],
        "is_featured": True,
        "is_active": True
    },
    {
        "name": "Vite + React + FastAPI",
        "slug": "vite-react-fastapi",
        "description": "Separated fullstack with Vite React frontend and FastAPI Python backend",
        "long_description": "Full-stack template with explicit separation: Vite + React for the frontend and FastAPI for the backend. Includes CORS setup, hot reload for both servers, PostgreSQL integration, and example CRUD API endpoints. Perfect for data science and ML applications.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-Vite-React-FastAPI-Base.git",
        "default_branch": "main",
        "category": "fullstack",
        "icon": "🐍",
        "tags": ["vite", "react", "fastapi", "python", "fullstack", "postgresql"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": ["Vite Frontend", "FastAPI Backend", "Dual Hot Reload", "CORS Configured", "PostgreSQL Ready", "Example CRUD API"],
        "tech_stack": ["Vite", "React", "FastAPI", "Python", "PostgreSQL"],
        "metadata": FRAMEWORK_METADATA["vite"],
        "is_featured": True,
        "is_active": True
    },
    {
        "name": "Vite + React + Go",
        "slug": "vite-react-go",
        "description": "High-performance fullstack with Vite React frontend and Go backend",
        "long_description": "Performance-focused fullstack template with Vite + React for the frontend and Go with Chi router for the backend. Includes Air for hot reloading, CORS middleware, example REST endpoints, and WebSocket support. Ideal for real-time applications and microservices.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-Vite-React-Go-Base.git",
        "default_branch": "main",
        "category": "fullstack",
        "icon": "🔷",
        "tags": ["vite", "react", "go", "golang", "fullstack", "chi-router", "websocket"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": ["Vite Frontend", "Go Backend", "Air Hot Reload", "Chi Router", "CORS Middleware", "WebSocket Support", "REST API"],
        "tech_stack": ["Vite", "React", "Go", "Chi Router", "Air"],
        "metadata": FRAMEWORK_METADATA["vite"],
        "is_featured": True,
        "is_active": True
    },
    {
        "name": "Expo",
        "slug": "expo-default",
        "description": "Cross-platform mobile app with Expo Router and React Native",
        "long_description": "Modern Expo starter template with file-based routing, React Native 0.81, React 19, and multi-platform support. Perfect for building iOS, Android, and web applications from a single codebase with hot reload and TypeScript. Features Expo Router for intuitive navigation and Metro bundler for optimized performance.",
        "git_repo_url": "https://github.com/TesslateAI/Studio-Expo-Base.git",
        "default_branch": "main",
        "category": "mobile",
        "icon": "📱",
        "tags": ["expo", "react-native", "mobile", "typescript", "ios", "android", "web", "metro"],
        "pricing_type": "free",
        "price": 0,
        "downloads": 0,
        "rating": 5.0,
        "reviews_count": 0,
        "features": ["File-based Routing", "Expo Router", "Multi-platform (iOS/Android/Web)", "Hot Reload", "TypeScript", "React Native 0.81", "Metro Bundler", "React 19"],
        "tech_stack": ["Expo SDK 54", "React Native 0.81", "React 19", "TypeScript", "Metro"],
        "metadata": FRAMEWORK_METADATA["expo"],
        "is_featured": True,
        "is_active": True
    }
]

TESSLATE_AGENT = {
    "name": "Tesslate Agent",
    "slug": "tesslate-agent",
    "description": "The official Tesslate autonomous software engineering agent",
    "long_description": """The official open source Tesslate Agent - a world-class autonomous AI software engineering agent that follows a clear Plan-Act-Observe-Verify methodology. This agent has deep expertise in system administration, operating system principles, network protocols, and software development across multiple languages.

This is the reference implementation that showcases Tesslate's core methodology and tool usage patterns. You can customize the model, fork it, or use it as a template for your own agents.

**Methodology:**
1. **Analyze & Plan**: Assess requirements and formulate step-by-step plans
2. **Execute**: Use tools to accomplish goals
3. **Observe & Verify**: Analyze outputs and verify success
4. **Self-Correct & Proceed**: Fix errors or move to next step
5. **Completion**: Signal when task is complete

**Features:**
- Comprehensive file operations (read, write, edit)
- Command execution with security controls
- Git operations and version control
- Multi-step task planning and execution
- Self-correction and error recovery""",
    "category": "fullstack",
    "system_prompt": TESSLATE_AGENT_SYSTEM_PROMPT,
    "mode": "agent",
    "agent_type": "IterativeAgent",
    "model": "gpt-4o-mini",
    "icon": "🤖",
    "preview_image": None,
    "pricing_type": "free",
    "price": 0,
    "source_type": "open",
    "is_forkable": True,
    "requires_user_keys": False,
    "features": [
        "Autonomous coding",
        "Multi-step planning",
        "File operations",
        "Command execution",
        "Git integration",
        "Self-correction"
    ],
    "required_models": ["gpt-4o-mini"],
    "tags": ["official", "autonomous", "fullstack", "open-source", "methodology"],
    "is_featured": True,
    "is_active": True,
    "tools": None  # Access to all tools
}


# =============================================================================
# SEED FUNCTIONS
# =============================================================================

async def seed_marketplace():
    """Seed marketplace bases and Tesslate Agent."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n" + "=" * 60)
        print("  TESSLATE MARKETPLACE SEEDER")
        print("=" * 60 + "\n")

        # --- Seed Bases ---
        print("📦 Seeding Marketplace Bases...\n")

        for base_data in MARKETPLACE_BASES:
            result = await db.execute(
                select(MarketplaceBase).where(MarketplaceBase.slug == base_data["slug"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  ✓ Base '{base_data['name']}' already exists (ID: {existing.id})")
            else:
                base = MarketplaceBase(**base_data)
                db.add(base)
                await db.commit()
                await db.refresh(base)
                print(f"  ✓ Created base '{base_data['name']}' (ID: {base.id})")

        # --- Seed Tesslate Agent ---
        print("\n🤖 Seeding Tesslate Agent...\n")

        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == TESSLATE_AGENT["slug"])
        )
        existing_agent = result.scalar_one_or_none()

        if existing_agent:
            print(f"  ✓ Agent '{TESSLATE_AGENT['name']}' already exists (ID: {existing_agent.id})")
            agent = existing_agent
        else:
            agent = MarketplaceAgent(**TESSLATE_AGENT)
            db.add(agent)
            await db.commit()
            await db.refresh(agent)
            print(f"  ✓ Created agent '{TESSLATE_AGENT['name']}' (ID: {agent.id})")

        # --- Auto-add Tesslate Agent to all users ---
        print("\n👥 Adding Tesslate Agent to all users...\n")

        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            result = await db.execute(
                select(UserPurchasedAgent).where(
                    UserPurchasedAgent.user_id == user.id,
                    UserPurchasedAgent.agent_id == agent.id
                )
            )
            existing = result.scalar_one_or_none()

            if not existing:
                purchase = UserPurchasedAgent(
                    user_id=user.id,
                    agent_id=agent.id,
                    purchase_type="free",
                    is_active=True
                )
                db.add(purchase)
                print(f"  ✓ Added to user '{user.username}'")
            else:
                print(f"  - User '{user.username}' already has agent")

        await db.commit()

        # --- Summary ---
        print("\n" + "=" * 60)
        print("  SUMMARY")
        print("=" * 60 + "\n")

        result = await db.execute(select(MarketplaceBase))
        bases = result.scalars().all()
        print(f"  📦 Bases: {len(bases)}")
        for base in bases:
            print(f"     - {base.name} ({base.slug})")

        result = await db.execute(select(MarketplaceAgent))
        agents = result.scalars().all()
        print(f"\n  🤖 Agents: {len(agents)}")
        for a in agents:
            print(f"     - {a.name} ({a.slug})")

        print("\n" + "=" * 60)
        print("  ✅ Seeding Complete!")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(seed_marketplace())
