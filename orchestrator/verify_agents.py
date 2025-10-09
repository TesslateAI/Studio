import asyncio
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine
from app.models import Agent

async def verify():
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(select(Agent))
        agents = result.scalars().all()
        print(f"Found {len(agents)} agents:")
        for agent in agents:
            print(f"  - {agent.name} ({agent.slug}) - mode: {agent.mode}")

asyncio.run(verify())
