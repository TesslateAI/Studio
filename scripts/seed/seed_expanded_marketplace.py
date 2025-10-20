"""
Seed Expanded Marketplace

Creates marketplace items across all categories:
- Agents (open and closed source versions)
- Bases (coming soon)
- Tools (coming soon)
- API Integrations (coming soon)
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from orchestrator.app.config import get_settings
from orchestrator.app.models import MarketplaceAgent, User, UserPurchasedAgent


MARKETPLACE_ITEMS = [
    # =========================================================================
    # AGENTS - Stream Builder (Open + Closed)
    # =========================================================================
    {
        "name": "Stream Builder (Open Source)",
        "slug": "stream-builder-open",
        "description": "Real-time streaming code generation with instant feedback",
        "long_description": "The Stream Builder agent generates code in real-time, streaming responses back to you as they're created. Perfect for quick prototyping and immediate feedback. **Open source**: Fork and customize to your needs!",
        "category": "builder",
        "item_type": "agent",
        "system_prompt": """You are an expert React developer. Generate clean, modern React code for Vite applications using Tailwind CSS.

CRITICAL RULES:
1. DO EXACTLY WHAT IS ASKED.
2. USE STANDARD TAILWIND CLASSES ONLY. No `bg-background` or `text-foreground`. Use `bg-white`, `text-black`, `bg-blue-500`, etc.
3. FILE COUNT LIMITS: A simple change should only modify 1-2 files.
4. NO ROUTING LIBRARIES like `react-router-dom` unless explicitly asked. Use `<a>` tags.
5. PRESERVATION IS KEY (for edits): Do not rewrite entire components. Integrate your changes surgically. Preserve all existing logic, props, and state.
6. COMPLETENESS: Each file must be COMPLETE from the first line to the last. NO "..." or truncation.
7. NO CONVERSATION: Your output must contain ONLY code wrapped in the specified format.
8. When providing code, ALWAYS specify the filename at the top of the code block like:
```javascript
// File: path/to/file.js
<code>
```""",
        "mode": "stream",
        "agent_type": "StreamAgent",
        "model": "cerebras/llama3.1-8b",
        "icon": "⚡",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Real-time streaming", "Instant feedback", "Code generation", "File editing"],
        "required_models": ["cerebras/llama3.1-8b"],
        "tags": ["react", "typescript", "tailwind", "streaming", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "Stream Builder (Pro)",
        "slug": "stream-builder-pro",
        "description": "Premium real-time streaming code generation with advanced features",
        "long_description": "The professional version of Stream Builder with enhanced capabilities, optimized prompts, and priority support. **Closed source**: Professionally maintained and optimized.",
        "category": "builder",
        "item_type": "agent",
        "system_prompt": """You are an expert React developer with advanced optimization capabilities. Generate clean, modern, production-ready React code for Vite applications using Tailwind CSS.

CRITICAL RULES:
1. DO EXACTLY WHAT IS ASKED.
2. USE STANDARD TAILWIND CLASSES ONLY. No `bg-background` or `text-foreground`. Use `bg-white`, `text-black`, `bg-blue-500`, etc.
3. FILE COUNT LIMITS: A simple change should only modify 1-2 files.
4. NO ROUTING LIBRARIES like `react-router-dom` unless explicitly asked. Use `<a>` tags.
5. PRESERVATION IS KEY (for edits): Do not rewrite entire components. Integrate your changes surgically. Preserve all existing logic, props, and state.
6. COMPLETENESS: Each file must be COMPLETE from the first line to the last. NO "..." or truncation.
7. NO CONVERSATION: Your output must contain ONLY code wrapped in the specified format.
8. PERFORMANCE: Optimize for performance, accessibility, and best practices.
9. When providing code, ALWAYS specify the filename at the top of the code block like:
```javascript
// File: path/to/file.js
<code>
```""",
        "mode": "stream",
        "agent_type": "StreamAgent",
        "model": "cerebras/llama3.1-8b",
        "icon": "⚡",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "requires_user_keys": False,
        "features": ["Real-time streaming", "Advanced optimization", "Production-ready code", "Priority support"],
        "required_models": ["cerebras/llama3.1-8b"],
        "tags": ["react", "typescript", "tailwind", "streaming", "professional"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },

    # =========================================================================
    # AGENTS - Full Stack Agent (Open + Closed)
    # =========================================================================
    {
        "name": "Full Stack Agent (Open Source)",
        "slug": "fullstack-agent-open",
        "description": "Autonomous agent with tool calling and iterative problem solving",
        "long_description": "The Full Stack Agent can read files, execute commands, and iteratively solve complex problems. It thinks, acts, and reflects until your task is complete. **Open source**: Fork and customize for your workflow!",
        "category": "fullstack",
        "item_type": "agent",
        "system_prompt": """You are an expert full-stack developer with access to tools.

Your capabilities:
- Read and write files
- Execute shell commands
- List directory contents
- Iteratively solve problems

Always:
1. Think before you act
2. Use tools to gather information
3. Make incremental changes
4. Verify your work
5. Signal TASK_COMPLETE when done

Format your thoughts clearly and use tools strategically.""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "cerebras/llama3.1-8b",
        "icon": "🤖",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "requires_user_keys": False,
        "features": ["Tool calling", "File operations", "Command execution", "Iterative problem solving"],
        "required_models": ["cerebras/llama3.1-8b"],
        "tags": ["fullstack", "autonomous", "tools", "iterative", "open-source"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },
    {
        "name": "Full Stack Agent (Pro)",
        "slug": "fullstack-agent-pro",
        "description": "Premium autonomous agent with advanced reasoning and optimization",
        "long_description": "The professional version of Full Stack Agent with enhanced reasoning, better error handling, and advanced optimization capabilities. **Closed source**: Enterprise-grade reliability.",
        "category": "fullstack",
        "item_type": "agent",
        "system_prompt": """You are an expert full-stack developer with advanced problem-solving capabilities and access to tools.

Your capabilities:
- Read and write files with error handling
- Execute shell commands with validation
- List directory contents with filtering
- Iteratively solve complex problems with optimization
- Advanced debugging and error recovery

Always:
1. Think strategically before acting
2. Use tools efficiently to gather information
3. Make incremental, validated changes
4. Verify your work with testing
5. Handle errors gracefully
6. Signal TASK_COMPLETE when done

Format your thoughts clearly, explain your reasoning, and use tools strategically.""",
        "mode": "agent",
        "agent_type": "IterativeAgent",
        "model": "cerebras/llama3.1-8b",
        "icon": "🤖",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "requires_user_keys": False,
        "features": ["Advanced reasoning", "Error handling", "Optimization", "Enterprise support"],
        "required_models": ["cerebras/llama3.1-8b"],
        "tags": ["fullstack", "autonomous", "tools", "professional", "enterprise"],
        "is_featured": True,
        "is_active": True,
        "tools": None
    },

    # =========================================================================
    # BASES (Coming Soon)
    # =========================================================================
    {
        "name": "SaaS Starter Kit",
        "slug": "saas-starter-base",
        "description": "Complete SaaS foundation with auth, billing, and dashboard",
        "long_description": "**Coming Soon** - A production-ready SaaS starter template with authentication, Stripe billing, user dashboard, and admin panel. Built with React, TypeScript, and Tailwind CSS.",
        "category": "saas",
        "item_type": "base",
        "icon": "🚀",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "features": ["Authentication", "Stripe billing", "User dashboard", "Admin panel"],
        "tags": ["saas", "starter", "template", "coming-soon"],
        "is_featured": True,
        "is_active": False,
    },
    {
        "name": "E-commerce Store",
        "slug": "ecommerce-base",
        "description": "Full-featured e-commerce store with cart and checkout",
        "long_description": "**Coming Soon** - Complete e-commerce solution with product catalog, shopping cart, checkout, and order management.",
        "category": "ecommerce",
        "item_type": "base",
        "icon": "🛒",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "features": ["Product catalog", "Shopping cart", "Checkout", "Order management"],
        "tags": ["ecommerce", "store", "template", "coming-soon"],
        "is_featured": True,
        "is_active": False,
    },

    # =========================================================================
    # TOOLS (Coming Soon)
    # =========================================================================
    {
        "name": "Database Schema Manager",
        "slug": "database-tool",
        "description": "Visual database schema designer and migration generator",
        "long_description": "**Coming Soon** - Design your database schema visually and automatically generate migrations for Prisma, Drizzle, or SQL.",
        "category": "database",
        "item_type": "tool",
        "icon": "🗄️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "features": ["Visual designer", "Migration generator", "Multi-ORM support"],
        "tags": ["database", "schema", "tool", "coming-soon"],
        "is_featured": True,
        "is_active": False,
    },
    {
        "name": "API Documentation Generator",
        "slug": "api-docs-tool",
        "description": "Auto-generate beautiful API documentation from your code",
        "long_description": "**Coming Soon** - Automatically generate interactive API documentation with examples and testing interface.",
        "category": "documentation",
        "item_type": "tool",
        "icon": "📚",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "features": ["Auto-generation", "Interactive docs", "Code examples", "Testing interface"],
        "tags": ["api", "documentation", "tool", "coming-soon"],
        "is_featured": True,
        "is_active": False,
    },

    # =========================================================================
    # INTEGRATIONS (Coming Soon)
    # =========================================================================
    {
        "name": "Stripe Payments",
        "slug": "stripe-integration",
        "description": "Integrate Stripe for one-time payments and subscriptions",
        "long_description": "**Coming Soon** - Complete Stripe integration with checkout, subscriptions, webhooks, and customer portal. Includes boilerplate code and helper functions.",
        "category": "payments",
        "item_type": "integration",
        "icon": "💳",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "features": ["One-time payments", "Subscriptions", "Webhooks", "Customer portal", "Boilerplate code"],
        "tags": ["stripe", "payments", "integration", "coming-soon"],
        "is_featured": True,
        "is_active": False,
    },
    {
        "name": "Google Maps",
        "slug": "google-maps-integration",
        "description": "Add maps, location search, and route calculation to your app",
        "long_description": "**Coming Soon** - Integrate Google Maps with tools for embedding maps, searching locations, geocoding, and calculating routes. Includes helper components and utilities.",
        "category": "maps",
        "item_type": "integration",
        "icon": "🗺️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "features": ["Map embedding", "Location search", "Geocoding", "Route calculation", "Helper components"],
        "tags": ["google-maps", "location", "integration", "coming-soon"],
        "is_featured": True,
        "is_active": False,
    },
]


async def seed_expanded_marketplace():
    """Seed expanded marketplace with all categories."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Clearing Old Marketplace Items ===\n")

        # Delete old items (except user-created forks)
        await db.execute(
            delete(UserPurchasedAgent)
        )
        await db.execute(
            delete(MarketplaceAgent).where(MarketplaceAgent.forked_by_user_id == None)
        )
        await db.commit()
        print("✓ Cleared old marketplace items\n")

        print("=== Seeding Expanded Marketplace ===\n")

        for item_data in MARKETPLACE_ITEMS:
            # Check if item exists
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == item_data["slug"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"✓ Item '{item_data['name']}' already exists (ID: {existing.id})")
            else:
                # Create item
                item = MarketplaceAgent(**item_data)
                db.add(item)
                await db.commit()
                await db.refresh(item)
                print(f"✓ Created {item_data['item_type']}: '{item_data['name']}' (ID: {item.id})")

        print("\n=== Auto-Adding Open Source Stream Builder to All Users ===\n")

        # Get open source Stream Builder
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == "stream-builder-open")
        )
        stream_agent = result.scalar_one_or_none()

        if not stream_agent:
            print("✗ Stream Builder (Open Source) not found!")
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
                print(f"  ✓ Added Stream Builder (Open Source) to user '{user.username}'")
            else:
                print(f"  - User '{user.username}' already has Stream Builder")

        await db.commit()

        print("\n=== Summary ===")

        # Count by item type
        result = await db.execute(select(MarketplaceAgent))
        all_items = result.scalars().all()

        by_type = {}
        for item in all_items:
            item_type = item.item_type or "agent"
            by_type[item_type] = by_type.get(item_type, 0) + 1

        print(f"Total marketplace items: {len(all_items)}")
        for item_type, count in by_type.items():
            print(f"  - {item_type}s: {count}")

        print()


if __name__ == "__main__":
    asyncio.run(seed_expanded_marketplace())
