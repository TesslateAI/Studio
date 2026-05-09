"""Unit tests for ``services.marketplace_agent_scope.resolve_agent_in_user_scope``.

Hermetic: alembic-migrated SQLite, no Redis / Docker / network. Verifies
the full decision matrix the picker / installer / worker depend on:

* missing → AgentScopeError(NOT_FOUND)
* skill / mcp_server / subagent / deployment_target → WRONG_TYPE
* is_active=False → INACTIVE
* system agent → returned regardless of library scope
* user has UserPurchasedAgent under their team → returned
* cross-team purchase under a different team → NOT_IN_LIBRARY
* superuser bypasses library scope
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy import insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001 - SA event signature
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def session_maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "agent_scope.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[1].parent
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)

    engine = create_async_engine(url, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())
    get_settings.cache_clear()


async def _seed_user(db, *, is_superuser: bool = False, default_team_id=None):
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"scope-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=is_superuser,
            is_verified=True,
            name="Scope User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
            default_team_id=default_team_id,
        )
    )
    await db.flush()
    return await db.get(User, user_id)


async def _seed_team(db) -> uuid.UUID:
    from app.models_team import Team

    team_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(Team.__table__).values(
            id=team_id,
            name=f"Team {suffix}",
            slug=f"team-{suffix}",
            is_personal=False,
        )
    )
    await db.flush()
    return team_id


# Mirror of alembic/versions/0088_marketplace_sources.py — system source
# row seeded by the migration so ``marketplace_agents.source_id`` (NOT
# NULL) has a valid FK to point at.
_TESSLATE_OFFICIAL_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _seed_agent(
    db,
    *,
    item_type: str = "agent",
    is_active: bool = True,
    is_system: bool = False,
) -> uuid.UUID:
    from app.models import MarketplaceAgent

    agent_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(MarketplaceAgent.__table__).values(
            id=agent_id,
            name=f"Agent {suffix}",
            slug=f"agent-{suffix}",
            description="Scope-test agent",
            category="builder",
            item_type=item_type,
            agent_type="IterativeAgent",
            pricing_type="free",
            source_id=_TESSLATE_OFFICIAL_SOURCE_ID,
            is_active=is_active,
            is_system=is_system,
            is_published=True,
        )
    )
    await db.flush()
    return agent_id


async def _link_purchase(db, *, agent_id, user_id, team_id=None) -> None:
    from app.models import UserPurchasedAgent

    await db.execute(
        core_insert(UserPurchasedAgent.__table__).values(
            id=uuid.uuid4(),
            user_id=user_id,
            team_id=team_id,
            agent_id=agent_id,
            purchase_type="free",
            is_active=True,
        )
    )
    await db.flush()


@pytest.mark.unit
def test_missing_agent_raises_not_found(session_maker) -> None:
    from app.services.marketplace_agent_scope import (
        AgentScopeError,
        resolve_agent_in_user_scope,
    )

    async def _run():
        async with session_maker() as db:
            user = await _seed_user(db)
            await db.commit()
            with pytest.raises(AgentScopeError) as exc_info:
                await resolve_agent_in_user_scope(
                    db, agent_id=uuid.uuid4(), user=user
                )
            assert exc_info.value.reason == AgentScopeError.REASON_NOT_FOUND

    asyncio.run(_run())


@pytest.mark.unit
@pytest.mark.parametrize(
    "wrong_type", ["skill", "mcp_server", "subagent", "deployment_target"]
)
def test_wrong_item_type_raises_wrong_type(session_maker, wrong_type) -> None:
    from app.services.marketplace_agent_scope import (
        AgentScopeError,
        resolve_agent_in_user_scope,
    )

    async def _run():
        async with session_maker() as db:
            user = await _seed_user(db)
            agent_id = await _seed_agent(db, item_type=wrong_type)
            await db.commit()
            with pytest.raises(AgentScopeError) as exc_info:
                await resolve_agent_in_user_scope(db, agent_id=agent_id, user=user)
            assert exc_info.value.reason == AgentScopeError.REASON_WRONG_TYPE

    asyncio.run(_run())


@pytest.mark.unit
def test_inactive_agent_raises_inactive(session_maker) -> None:
    from app.services.marketplace_agent_scope import (
        AgentScopeError,
        resolve_agent_in_user_scope,
    )

    async def _run():
        async with session_maker() as db:
            user = await _seed_user(db)
            agent_id = await _seed_agent(db, is_active=False)
            await db.commit()
            with pytest.raises(AgentScopeError) as exc_info:
                await resolve_agent_in_user_scope(db, agent_id=agent_id, user=user)
            assert exc_info.value.reason == AgentScopeError.REASON_INACTIVE

    asyncio.run(_run())


@pytest.mark.unit
def test_system_agent_resolves_without_purchase(session_maker) -> None:
    from app.services.marketplace_agent_scope import resolve_agent_in_user_scope

    async def _run():
        async with session_maker() as db:
            user = await _seed_user(db)
            agent_id = await _seed_agent(db, is_system=True)
            await db.commit()
            agent = await resolve_agent_in_user_scope(
                db, agent_id=agent_id, user=user
            )
            assert agent.id == agent_id

    asyncio.run(_run())


@pytest.mark.unit
def test_purchased_agent_in_team_resolves(session_maker) -> None:
    from app.services.marketplace_agent_scope import resolve_agent_in_user_scope

    async def _run():
        async with session_maker() as db:
            team_id = await _seed_team(db)
            user = await _seed_user(db, default_team_id=team_id)
            agent_id = await _seed_agent(db)
            await _link_purchase(
                db, agent_id=agent_id, user_id=user.id, team_id=team_id
            )
            await db.commit()
            agent = await resolve_agent_in_user_scope(
                db, agent_id=agent_id, user=user
            )
            assert agent.id == agent_id

    asyncio.run(_run())


@pytest.mark.unit
def test_cross_team_purchase_raises_not_in_library(session_maker) -> None:
    """The exact TC-03 Bug #21 surface — team A user binding team B's agent."""
    from app.services.marketplace_agent_scope import (
        AgentScopeError,
        resolve_agent_in_user_scope,
    )

    async def _run():
        async with session_maker() as db:
            team_a = await _seed_team(db)
            team_b = await _seed_team(db)
            user_a = await _seed_user(db, default_team_id=team_a)
            user_b = await _seed_user(db, default_team_id=team_b)
            agent_id = await _seed_agent(db)
            # Agent purchased only by team B.
            await _link_purchase(
                db, agent_id=agent_id, user_id=user_b.id, team_id=team_b
            )
            await db.commit()
            with pytest.raises(AgentScopeError) as exc_info:
                await resolve_agent_in_user_scope(
                    db, agent_id=agent_id, user=user_a
                )
            assert exc_info.value.reason == AgentScopeError.REASON_NOT_IN_LIBRARY

    asyncio.run(_run())


@pytest.mark.unit
def test_superuser_bypasses_library_check(session_maker) -> None:
    from app.services.marketplace_agent_scope import resolve_agent_in_user_scope

    async def _run():
        async with session_maker() as db:
            superuser = await _seed_user(db, is_superuser=True)
            agent_id = await _seed_agent(db)  # no purchase row
            await db.commit()
            agent = await resolve_agent_in_user_scope(
                db, agent_id=agent_id, user=superuser
            )
            assert agent.id == agent_id

    asyncio.run(_run())
