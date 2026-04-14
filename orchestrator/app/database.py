from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool

from .config import get_settings

settings = get_settings()


def _build_engine_kwargs(database_url: str) -> dict:
    """Backend-specific engine kwargs.

    Postgres (cloud) keeps pooling + SSL + server hints.
    SQLite (desktop sidecar) uses StaticPool + check_same_thread=False
    so the single-file DB works cleanly under async.
    """
    if database_url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    if database_url.startswith("postgresql"):
        return {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "connect_args": {
                "ssl": "require" if settings.database_ssl else False,
                "command_timeout": 60,
                "server_settings": {"jit": "off"},
            },
        }
    return {}


engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    **_build_engine_kwargs(settings.database_url),
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
