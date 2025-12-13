"""Update agent mode for testing"""
import asyncio
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine
from app.models import Agent

async def update_mode():
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Update Frontend Builder to agent mode
        await session.execute(
            update(Agent)
            .where(Agent.slug == 'frontend-builder')
            .values(mode='agent')
        )
        await session.commit()

        # Verify
        result = await session.execute(select(Agent))
        agents = result.scalars().all()
        print(f"Updated agents:")
        for agent in agents:
            print(f"  - {agent.name} ({agent.slug}) - mode: {agent.mode}")

asyncio.run(update_mode())
