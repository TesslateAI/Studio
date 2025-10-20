"""
Seed Marketplace Agents

Creates default agents in the marketplace:
- StreamAgent (free, auto-added to all users)
- IterativeAgent (free, can be added to account)
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
        "icon": "⚡",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "requires_user_keys": False,
        "features": ["Real-time streaming", "Instant feedback", "Code generation", "File editing"],
        "required_models": ["gpt-4", "claude-3", "cerebras/llama"],
        "tags": ["react", "typescript", "tailwind", "streaming"],
        "is_featured": True,
        "is_active": True,
        "tools": None  # Uses all tools (no restriction)
    },
    {
        "name": "Full Stack Agent",
        "slug": "fullstack-agent",
        "description": "Autonomous agent with tool calling and iterative problem solving",
        "long_description": "The Full Stack Agent can read files, execute commands, and iteratively solve complex problems. It thinks, acts, and reflects until your task is complete.",
        "category": "fullstack",
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
        "icon": "🤖",
        "preview_image": None,
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "requires_user_keys": False,
        "features": ["Tool calling", "File operations", "Command execution", "Iterative problem solving"],
        "required_models": ["gpt-4", "claude-3", "cerebras/llama"],
        "tags": ["fullstack", "autonomous", "tools", "iterative"],
        "is_featured": True,
        "is_active": True,
        "tools": None  # Uses all tools
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
