"""
Delete All Marketplace Agents

This script deletes all marketplace agents and user-agent associations from the database.

HOW TO RUN:
-----------
Docker:
  docker cp scripts/seed/delete_all_agents.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/delete_all_agents.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
import sys
import os

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings
from app.models import MarketplaceAgent, UserPurchasedAgent, MarketplaceTransaction


async def delete_all_agents():
    """Delete all marketplace agents and user associations."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Deleting All Marketplace Agents ===\n")

        # First, delete all marketplace transactions (foreign key constraint)
        result = await db.execute(select(MarketplaceTransaction))
        transactions = result.scalars().all()
        transaction_count = len(transactions)

        await db.execute(delete(MarketplaceTransaction))
        print(f"✓ Deleted {transaction_count} marketplace transactions")

        # Second, delete all user-agent associations
        result = await db.execute(select(UserPurchasedAgent))
        user_agents = result.scalars().all()
        user_agent_count = len(user_agents)

        await db.execute(delete(UserPurchasedAgent))
        print(f"✓ Deleted {user_agent_count} user-agent associations")

        # Finally, delete all marketplace agents
        result = await db.execute(select(MarketplaceAgent))
        agents = result.scalars().all()
        agent_count = len(agents)

        for agent in agents:
            print(f"  - Deleting '{agent.name}' (slug: {agent.slug})")

        await db.execute(delete(MarketplaceAgent))
        print(f"\n✓ Deleted {agent_count} marketplace agents")

        await db.commit()

        print("\n=== Verification ===")
        result = await db.execute(select(MarketplaceAgent))
        remaining_agents = result.scalars().all()
        print(f"Remaining marketplace agents: {len(remaining_agents)}")

        result = await db.execute(select(UserPurchasedAgent))
        remaining_user_agents = result.scalars().all()
        print(f"Remaining user-agent associations: {len(remaining_user_agents)}")
        print()


if __name__ == "__main__":
    asyncio.run(delete_all_agents())
