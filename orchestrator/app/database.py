from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,  # Disable SQL query logging to reduce noise
    future=True,
    pool_pre_ping=True,  # Validate connections before use
    pool_recycle=3600,   # Recycle connections every hour
    connect_args={
        "ssl": False,  # Disable SSL for internal cluster connections
        "command_timeout": 60,  # 60 second command timeout
        "server_settings": {
            "jit": "off"  # Disable JIT for better connection stability
        }
    } if settings.database_url.startswith("postgresql") else {}
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()