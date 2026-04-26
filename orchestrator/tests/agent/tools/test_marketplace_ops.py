"""Phase 5 — unit tests for ``agent.tools.marketplace_ops``.

Covers the four tool surfaces with the highest-risk semantics:

- ``create_agent`` writes ``is_published=False`` and stamps
  ``created_by_automation_id`` from context.
- ``update_agent`` rejects published rows.
- ``attach_schedule`` rejects depth-2 attempts (parent.depth=1).
- ``attach_schedule`` rejects child contracts carrying non-positive-list
  scopes.

Fixture pattern mirrors the existing dispatcher / budget tests.
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
from sqlalchemy import event, insert as core_insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration fixture (mirror of test_dispatcher / test_budget).
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "marketplace_ops.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers.
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"mo-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="MO User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation(
    db,
    *,
    owner_user_id: uuid.UUID,
    depth: int = 0,
    parent_automation_id: uuid.UUID | None = None,
    contract: dict | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name=f"automation-{uuid.uuid4().hex[:6]}",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract=contract
        if contract is not None
        else {
            "allowed_tools": ["read_file"],
            "allowed_scopes": ["read_file", "write_file"],
            "max_compute_tier": 0,
            "max_spend_per_run_usd": "1.00",
            "on_breach": "pause_for_approval",
        },
        max_compute_tier=0,
        max_spend_per_run_usd=1,
        depth=depth,
        parent_automation_id=parent_automation_id,
        is_active=True,
    )
    db.add(autom)
    await db.flush()
    return autom.id


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_inserts_draft_with_provenance(session_maker):
    from app.agent.tools.marketplace_ops.create_agent import create_agent_executor
    from app.auth.scopes import MARKETPLACE_AUTHOR
    from app.models import MarketplaceAgent

    async with session_maker() as db:
        user_id = await _seed_user(db)
        automation_id = await _seed_automation(db, owner_user_id=user_id)
        await db.commit()

        result = await create_agent_executor(
            params={
                "name": "Daily Standup Digester",
                "description": "Summarises overnight Slack chatter",
                "system_prompt": "You are a quiet, careful summariser.",
                "model": "gpt-4o-mini",
                "tool_allowlist": ["read_file", "send_message"],
                "category": "automation",
            },
            context={
                "db": db,
                "user_id": user_id,
                "automation_id": automation_id,
                "allowed_scopes": [MARKETPLACE_AUTHOR],
            },
        )

        assert result["success"] is True
        assert result["is_published"] is False
        assert "agent_id" in result

        # Re-load and verify provenance + draft state.
        agent_id = uuid.UUID(result["agent_id"])
        row = (
            await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
            )
        ).scalar_one()
        assert row.is_published is False
        assert row.created_by_automation_id == automation_id
        assert row.created_by_user_id == user_id
        assert row.item_type == "agent"


@pytest.mark.asyncio
async def test_create_agent_missing_scope_rejected(session_maker):
    from app.agent.tools.marketplace_ops.create_agent import create_agent_executor

    async with session_maker() as db:
        user_id = await _seed_user(db)
        await db.commit()

        result = await create_agent_executor(
            params={
                "name": "Sneaky",
                "description": "Tries to bypass the scope gate",
                "system_prompt": "...",
            },
            context={
                "db": db,
                "user_id": user_id,
                # Allowed scopes set explicitly without MARKETPLACE_AUTHOR.
                "allowed_scopes": ["read_file"],
            },
        )

        assert result["success"] is False
        assert "marketplace.author" in result["message"]


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_agent_rejects_published_row(session_maker):
    from app.agent.tools.marketplace_ops.update_agent import update_agent_executor
    from app.auth.scopes import MARKETPLACE_AUTHOR
    from app.models import MarketplaceAgent

    async with session_maker() as db:
        user_id = await _seed_user(db)
        # Insert a published agent owned by user.
        agent = MarketplaceAgent(
            id=uuid.uuid4(),
            name="Already Published",
            slug=f"published-{uuid.uuid4().hex[:6]}",
            description="d",
            category="custom",
            item_type="agent",
            forked_by_user_id=user_id,
            created_by_user_id=user_id,
            pricing_type="free",
            is_published=True,
        )
        db.add(agent)
        await db.commit()

        result = await update_agent_executor(
            params={
                "agent_id": str(agent.id),
                "patch": {"description": "tweaked"},
            },
            context={
                "db": db,
                "user_id": user_id,
                "allowed_scopes": [MARKETPLACE_AUTHOR],
            },
        )

        assert result["success"] is False
        assert "published" in result["message"]


@pytest.mark.asyncio
async def test_update_agent_rejects_forbidden_field(session_maker):
    from app.agent.tools.marketplace_ops.update_agent import update_agent_executor
    from app.auth.scopes import MARKETPLACE_AUTHOR
    from app.models import MarketplaceAgent

    async with session_maker() as db:
        user_id = await _seed_user(db)
        agent = MarketplaceAgent(
            id=uuid.uuid4(),
            name="Draft",
            slug=f"draft-{uuid.uuid4().hex[:6]}",
            description="d",
            category="custom",
            item_type="agent",
            forked_by_user_id=user_id,
            created_by_user_id=user_id,
            pricing_type="free",
            is_published=False,
        )
        db.add(agent)
        await db.commit()

        result = await update_agent_executor(
            params={
                "agent_id": str(agent.id),
                "patch": {
                    "description": "ok",
                    # Forbidden field — should reject the whole call.
                    "is_published": True,
                },
            },
            context={
                "db": db,
                "user_id": user_id,
                "allowed_scopes": [MARKETPLACE_AUTHOR],
            },
        )

        assert result["success"] is False
        assert "is_published" in result["message"]


# ---------------------------------------------------------------------------
# attach_schedule
# ---------------------------------------------------------------------------


async def _seed_owned_agent(db, user_id: uuid.UUID):
    from app.models import MarketplaceAgent

    agent = MarketplaceAgent(
        id=uuid.uuid4(),
        name="Owned",
        slug=f"owned-{uuid.uuid4().hex[:6]}",
        description="d",
        category="custom",
        item_type="agent",
        forked_by_user_id=user_id,
        created_by_user_id=user_id,
        pricing_type="free",
        is_published=False,
    )
    db.add(agent)
    await db.flush()
    return agent.id


@pytest.mark.asyncio
async def test_attach_schedule_rejects_depth_two_attempt(session_maker):
    """Parent at depth=1 → child would be depth=2 → reject."""
    from app.agent.tools.marketplace_ops.attach_schedule import (
        attach_schedule_executor,
    )
    from app.auth.scopes import AUTOMATIONS_WRITE

    async with session_maker() as db:
        user_id = await _seed_user(db)
        # depth=1 parent. The DB CHECK only allows 0 or 1, so this is
        # the maximum legal depth; any child would be depth=2.
        parent_id = await _seed_automation(db, owner_user_id=user_id, depth=1)
        agent_id = await _seed_owned_agent(db, user_id)
        await db.commit()

        result = await attach_schedule_executor(
            params={
                "agent_id": str(agent_id),
                "trigger": {"kind": "manual", "config": {}},
                "prompt_template": "do the thing",
                "contract": {
                    "allowed_scopes": ["read_file"],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "0.50",
                },
            },
            context={
                "db": db,
                "user_id": user_id,
                "automation_id": parent_id,
                "allowed_scopes": [AUTOMATIONS_WRITE],
            },
        )

        assert result["success"] is False
        assert "depth_exceeded" in result["message"]


@pytest.mark.asyncio
async def test_attach_schedule_rejects_non_inheritable_scope(session_maker):
    from app.agent.tools.marketplace_ops.attach_schedule import (
        attach_schedule_executor,
    )
    from app.auth.scopes import AUTOMATIONS_WRITE, MARKETPLACE_AUTHOR

    async with session_maker() as db:
        user_id = await _seed_user(db)
        parent_id = await _seed_automation(db, owner_user_id=user_id, depth=0)
        agent_id = await _seed_owned_agent(db, user_id)
        await db.commit()

        result = await attach_schedule_executor(
            params={
                "agent_id": str(agent_id),
                "trigger": {"kind": "manual", "config": {}},
                "prompt_template": "do the thing",
                "contract": {
                    # MARKETPLACE_AUTHOR is non-inheritable — must reject.
                    "allowed_scopes": ["read_file", MARKETPLACE_AUTHOR],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "0.50",
                },
            },
            context={
                "db": db,
                "user_id": user_id,
                "automation_id": parent_id,
                "allowed_scopes": [AUTOMATIONS_WRITE],
            },
        )

        assert result["success"] is False
        assert "scope_not_inheritable" in result["message"]


@pytest.mark.asyncio
async def test_attach_schedule_clean_child_succeeds(session_maker):
    """Happy path: depth=0 parent + clean child + matching cap → success."""
    from app.agent.tools.marketplace_ops.attach_schedule import (
        attach_schedule_executor,
    )
    from app.auth.scopes import AUTOMATIONS_WRITE
    from app.models_automations import AutomationDefinition

    async with session_maker() as db:
        user_id = await _seed_user(db)
        parent_id = await _seed_automation(db, owner_user_id=user_id, depth=0)
        agent_id = await _seed_owned_agent(db, user_id)
        await db.commit()

        result = await attach_schedule_executor(
            params={
                "agent_id": str(agent_id),
                "trigger": {"kind": "cron", "config": {"expression": "0 9 * * *"}},
                "prompt_template": "morning summary",
                "contract": {
                    "allowed_scopes": ["read_file"],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "0.50",
                },
                "name": "morning-digest",
            },
            context={
                "db": db,
                "user_id": user_id,
                "automation_id": parent_id,
                "allowed_scopes": [AUTOMATIONS_WRITE],
            },
        )

        assert result["success"] is True, result
        assert result["depth"] == 1
        assert result["is_active"] is False  # draft until UI flips it

        # Verify the child row was created with the right link + depth.
        child_id = uuid.UUID(result["automation_id"])
        child = (
            await db.execute(
                select(AutomationDefinition).where(
                    AutomationDefinition.id == child_id
                )
            )
        ).scalar_one()
        assert child.depth == 1
        assert child.parent_automation_id == parent_id
        assert child.is_active is False
