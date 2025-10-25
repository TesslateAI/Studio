"""
Create all database tables with UUID schema
"""
import asyncio
from app.database import engine, Base
from app.models import *
from app.models_kanban import *


async def create_tables():
    """Create all tables with UUID primary keys."""
    print("Creating all tables with UUID schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ All tables created successfully!")


if __name__ == "__main__":
    asyncio.run(create_tables())
