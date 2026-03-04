"""Check and display current marketplace bases"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import get_settings
from app.models import MarketplaceBase

async def check_bases():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MarketplaceBase))
        bases = result.scalars().all()

        print('Current Marketplace Bases:')
        print('=' * 80)
        for base in bases:
            print(f'ID: {base.id}')
            print(f'Name: {base.name}')
            print(f'Slug: {base.slug}')
            print(f'Pricing: {base.pricing_type} (${base.price})')
            print(f'Active: {base.is_active}')
            print(f'Featured: {base.is_featured}')
            print('=' * 80)

if __name__ == "__main__":
    asyncio.run(check_bases())
