import asyncio
from app.database import AsyncSessionLocal
from app.models import MarketplaceAgent
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MarketplaceAgent))
        agents = result.scalars().all()
        print(f'Found {len(agents)} agents in database:')
        for a in agents:
            print(f'  - {a.name} ({a.slug}) - is_active: {a.is_active}, featured: {a.is_featured}')

        # Check how many are active
        active_result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.is_active == True))
        active_agents = active_result.scalars().all()
        print(f'\nActive agents: {len(active_agents)}')

asyncio.run(check())