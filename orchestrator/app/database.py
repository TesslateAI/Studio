from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.functions import now as _sa_now

from .config import get_settings


# SQLite has no built-in now() — translate to CURRENT_TIMESTAMP.
# Postgres / others keep their native dialect rendering. This lets every
# model use func.now() unchanged across both backends.
@compiles(_sa_now, "sqlite")
def _compile_now_sqlite(_element, _compiler, **_kw):
    return "CURRENT_TIMESTAMP"


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


# Migrations bake `server_default=sa.text("now()")` into many tables. SQLite
# has no built-in now() function, so register a UDF that returns ISO-8601
# UTC. Runs on every fresh aiosqlite connection.
if settings.database_url.startswith("sqlite"):
    import datetime as _dt

    from sqlalchemy import event as _event

    @_event.listens_for(engine.sync_engine, "connect")
    def _register_now_udf(dbapi_conn, _conn_record):
        # Alembic migrations bake server_default=text("now()") into schema;
        # SQLite has no built-in now(). Supply one per connection.
        dbapi_conn.create_function("now", 0, lambda: _dt.datetime.now(_dt.UTC).isoformat(sep=" "))


def ensure_aware(value):
    """Coerce a possibly-naive datetime to tz-aware UTC.

    SQLite's aiosqlite driver returns DateTime(timezone=True) columns as
    naive ``datetime`` (no tzinfo), while Postgres returns them aware.
    Code that compares such values against ``datetime.now(UTC)`` raises
    ``TypeError: can't compare offset-naive and offset-aware datetimes``
    on SQLite. Call this helper at the comparison site.
    """
    import datetime as _dt

    if value is None:
        return None
    if isinstance(value, _dt.datetime) and value.tzinfo is None:
        return value.replace(tzinfo=_dt.UTC)
    return value


AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
