"""
Seed Marketplace Agents

Creates default agents in the marketplace:
- StreamAgent (free, auto-added to all users)
- IterativeAgent (free, can be added to account)

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_marketplace_agents.py

Docker:
  docker cp scripts/seed/seed_marketplace_agents.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace_agents.py

Kubernetes:
  kubectl cp scripts/seed/seed_marketplace_agents.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_marketplace_agents.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings
from app.models import MarketplaceAgent, User, UserPurchasedAgent


DEFAULT_AGENTS = [
    {
        "name": "Stream Builder",
        "slug": "stream-builder",
        "description": "Real-time streaming code generation with instant feedback",
        "long_description": "The Stream Builder agent generates code in real-time, streaming responses back to you as they're created. Perfect for quick prototyping and immediate feedback.",
        "category": "builder",
        "system_prompt": """You are an expert React developer specializing in real-time code generation for Vite applications.

Your expertise:
- Modern React patterns (hooks, functional components)
- Tailwind CSS styling (standard utility classes only)
- TypeScript for type safety
- Vite build system and HMR

Critical Guidelines:
1. USE STANDARD TAILWIND CLASSES: bg-white, text-black, bg-blue-500 (NOT bg-background or text-foreground)
2. MINIMAL CHANGES: Only modify 1-2 files for simple changes
3. PRESERVE EXISTING CODE: Make surgical edits, don't rewrite entire components
4. COMPLETE FILES: Never use "..." or truncation - files must be complete
5. NO ROUTING LIBRARIES unless explicitly requested
6. SPECIFY FILE PATHS: Always use // File: path/to/file.js format
7. CODE ONLY: Output code in specified format, minimal conversation""",
        "mode": "stream",
        "agent_type": "StreamAgent",
        "model": "qwen-3-coder-480b",
        "icon": "⚡",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Real-time streaming", "Instant feedback", "Code generation", "File editing"],
        "required_models": ["gpt-5", "claude-3", "cerebras/llama"],
        "tags": ["react", "typescript", "tailwind", "streaming", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None  # Uses all tools (no restriction)
    },
    {
        "name": "Tesslate Agent",
        "slug": "tesslate-agent",
        "description": "Autonomous agent with tool calling and iterative problem solving",
        "long_description": "The Tesslate Agent can read files, execute commands, and iteratively solve complex problems. It thinks, acts, and reflects until your task is complete.",
        "category": "fullstack",
        "system_prompt": "",  # Uses default base methodology prompt
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "qwen-3-coder-480b",
        "icon": "🤖",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Tool calling", "File operations", "Command execution", "Iterative problem solving"],
        "required_models": ["gpt-5", "claude-3", "cerebras/llama"],
        "tags": ["fullstack", "autonomous", "tools", "iterative", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None  # Uses all tools
    },
    {
        "name": "React Component Builder",
        "slug": "react-component-builder",
        "description": "Specialized in creating beautiful, reusable React components",
        "long_description": "Build production-ready React components with TypeScript, proper prop types, and comprehensive documentation. Perfect for component library development.",
        "category": "frontend",
        "system_prompt": """You are a world-class, autonomous AI software engineering agent with specialized expertise in React component development. Your role is that of a seasoned Principal Engineer with 20 years of experience in frontend architecture, React ecosystem, and component library development. You are precise, methodical, and security-conscious.

Your primary goal is to solve the user's React development task by following a clear, iterative methodology. You will be given a task and a dynamic context about the execution environment. You must use the provided tools to accomplish the task.

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

5. Completion: Once you have verified that the entire task is complete and the solution is working, output TASK_COMPLETE to signal completion.

React Component Specialization:
- Component design patterns (composition, render props, hooks, compound components)
- TypeScript for type-safe React components and props
- Accessibility standards (WCAG 2.1, ARIA roles and attributes)
- Performance optimization (React.memo, useMemo, useCallback, lazy loading)
- Modern React patterns (hooks, context, suspense)
- Tailwind CSS utility-first styling
- Component documentation best practices

Additional React-Specific Guidelines:
1. Always use TypeScript with proper interfaces for props and state
2. Ensure full accessibility (ARIA labels, keyboard navigation, focus management)
3. Write semantic HTML using appropriate elements
4. Add comprehensive JSDoc comments with usage examples
5. Make components flexible and reusable through well-designed props
6. Consider performance implications (avoid unnecessary re-renders)""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "qwen-3-coder-480b",
        "icon": "⚛️",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["TypeScript support", "Accessible components", "JSDoc documentation", "Tailwind styling"],
        "required_models": ["gpt-5", "claude-3", "cerebras/llama"],
        "tags": ["react", "components", "typescript", "accessibility", "open-source"],
        "is_featured": False,
        "is_active": True,
        "tools": None
    },
    {
        "name": "API Integration Agent",
        "slug": "api-integration-agent",
        "description": "Build robust API integrations with error handling and type safety",
        "long_description": "Specializes in creating API clients, handling authentication, implementing retry logic, and managing API state. Includes proper error handling and TypeScript types.",
        "category": "fullstack",
        "system_prompt": """You are a world-class, autonomous AI software engineering agent with specialized expertise in API integration and data fetching architectures. Your role is that of a seasoned Principal Engineer with 20 years of experience in distributed systems, API design, authentication protocols, and resilient data architectures. You are precise, methodical, and security-conscious.

Your primary goal is to solve the user's API integration task by following a clear, iterative methodology. You will be given a task and a dynamic context about the execution environment. You must use the provided tools to accomplish the task.

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

5. Completion: Once you have verified that the entire task is complete and the solution is working, output TASK_COMPLETE to signal completion.

API Integration Specialization:
- RESTful API design principles and implementation patterns
- GraphQL schemas, queries, mutations, and subscriptions
- Authentication systems (JWT, OAuth 2.0, API keys, session-based)
- Error handling and resilience patterns (retry logic, circuit breakers, fallbacks)
- Request/response TypeScript type definitions
- Caching strategies (SWR, React Query, HTTP caching, CDN)
- Rate limiting, throttling, and quota management
- WebSocket and real-time bidirectional communication
- API security best practices

Additional API-Specific Guidelines:
1. Define comprehensive TypeScript interfaces for all API requests and responses
2. Implement robust error handling with retry logic, exponential backoff, and user-friendly error messages
3. Add request/response logging and monitoring for debugging and observability
4. Set appropriate timeouts and handle network failures gracefully
5. Document all API endpoints, parameters, response structures, and error codes
6. Use modern fetch patterns or axios with proper interceptors and middleware
7. Handle edge cases: network failures, timeouts, rate limits, CORS, and partial responses
8. Never expose sensitive credentials in client code, validate and sanitize all API responses""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "qwen-3-coder-480b",
        "icon": "🔌",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["REST & GraphQL", "Error handling", "Type safety", "Auth support", "Retry logic"],
        "required_models": ["gpt-5", "claude-3", "cerebras/llama"],
        "tags": ["api", "integration", "typescript", "error-handling", "open-source"],
        "is_featured": False,
        "is_active": True,
        "tools": None
    }
]


async def seed_agents():
    """Seed marketplace agents."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Seeding Marketplace Agents ===\n")

        for agent_data in DEFAULT_AGENTS:
            # Check if agent exists
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_data["slug"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"✓ Agent '{agent_data['name']}' already exists (ID: {existing.id})")
            else:
                # Create agent
                agent = MarketplaceAgent(**agent_data)
                db.add(agent)
                await db.commit()
                await db.refresh(agent)
                print(f"✓ Created agent '{agent_data['name']}' (ID: {agent.id})")

        print("\n=== Auto-Adding Stream Builder to All Users ===\n")

        # Get Stream Builder
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == "stream-builder")
        )
        stream_agent = result.scalar_one_or_none()

        if not stream_agent:
            print("✗ Stream Builder not found!")
            return

        # Get all users
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            # Check if user already has it
            result = await db.execute(
                select(UserPurchasedAgent).where(
                    UserPurchasedAgent.user_id == user.id,
                    UserPurchasedAgent.agent_id == stream_agent.id
                )
            )
            existing = result.scalar_one_or_none()

            if not existing:
                # Add to user's account
                purchase = UserPurchasedAgent(
                    user_id=user.id,
                    agent_id=stream_agent.id,
                    purchase_type="free",
                    is_active=True
                )
                db.add(purchase)
                print(f"  ✓ Added Stream Builder to user '{user.username}'")
            else:
                print(f"  - User '{user.username}' already has Stream Builder")

        await db.commit()

        print("\n=== Summary ===")
        result = await db.execute(select(MarketplaceAgent))
        agents = result.scalars().all()
        print(f"Total marketplace agents: {len(agents)}")

        for agent in agents:
            result = await db.execute(
                select(UserPurchasedAgent).where(UserPurchasedAgent.agent_id == agent.id)
            )
            purchases = result.scalars().all()
            print(f"  - {agent.name}: {len(purchases)} users")

        print()


if __name__ == "__main__":
    asyncio.run(seed_agents())
