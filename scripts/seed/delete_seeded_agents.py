"""
Delete Seeded Marketplace Agents

Removes all seeded marketplace agents and their associated user purchases.

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/delete_seeded_agents.py

Docker:
  docker cp scripts/seed/delete_seeded_agents.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/delete_seeded_agents.py

Kubernetes:
  kubectl cp scripts/seed/delete_seeded_agents.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/delete_seeded_agents.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
import sys
import os

# Add parent directories to path
orchestrator_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'orchestrator')
sys.path.insert(0, orchestrator_path)

from app.config import get_settings
from app.models import MarketplaceAgent, UserPurchasedAgent


SEEDED_AGENT_SLUGS = [
    "stream-builder",
    "fullstack-agent",
    "tesslate-agent",
    "react-component-builder",
    "api-integration-agent"
]


async def delete_agents():
    """Delete seeded marketplace agents."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        print("\n=== Deleting Seeded Marketplace Agents ===\n")

        for slug in SEEDED_AGENT_SLUGS:
            # Find agent
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
            )
            agent = result.scalar_one_or_none()

            if agent:
                # Delete associated user purchases first
                result = await db.execute(
                    select(UserPurchasedAgent).where(UserPurchasedAgent.agent_id == agent.id)
                )
                purchases = result.scalars().all()

                if purchases:
                    await db.execute(
                        delete(UserPurchasedAgent).where(UserPurchasedAgent.agent_id == agent.id)
                    )
                    print(f"  ✓ Deleted {len(purchases)} user purchases for '{agent.name}'")

                # Delete the agent
                await db.delete(agent)
                print(f"✓ Deleted agent '{agent.name}' (slug: {slug})")
            else:
                print(f"- Agent with slug '{slug}' not found, skipping")

        await db.commit()
        print("\n=== Deletion Complete ===\n")


if __name__ == "__main__":
    asyncio.run(delete_agents())
