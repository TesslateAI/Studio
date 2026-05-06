"""Tests for the is_system flag on MarketplaceAgent.

Verifies that agents marked is_system=True are excluded from all
user-facing agent selection endpoints while regular agents still appear.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_system_agent.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()

    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)

    yield url
    get_settings.cache_clear()


@pytest.fixture
def db_setup(migrated_sqlite):
    """Returns (app, async_sessionmaker, engine) wired to the migrated SQLite DB."""
    from app.database import get_db
    from app.routers import marketplace
    from app.users import current_active_user, current_optional_user

    engine = create_async_engine(migrated_sqlite, future=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with maker() as s:
            yield s

    fake_user = Mock()
    fake_user.id = uuid.uuid4()
    fake_user.default_team_id = None

    app = FastAPI()
    app.include_router(marketplace.router, prefix="/api/marketplace")
    app.dependency_overrides[current_active_user] = lambda: fake_user
    app.dependency_overrides[current_optional_user] = lambda: fake_user
    app.dependency_overrides[get_db] = override_db

    yield app, maker, engine, fake_user

    asyncio.run(engine.dispose())


_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_agent(*, slug: str, is_system: bool = False) -> dict:
    return {
        "id": uuid.uuid4(),
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "description": f"Test agent {slug}",
        "category": "builder",
        "item_type": "agent",
        "pricing_type": "free",
        "price": 0,
        "is_active": True,
        "is_published": True,
        "is_system": is_system,
        "icon": "🤖",
        "created_at": _NOW,
        "updated_at": _NOW,
    }


async def _seed(maker, fake_user_id):
    """Insert one system agent and one regular agent, both owned by fake_user."""
    from app.models import MarketplaceAgent, UserPurchasedAgent

    system_agent = MarketplaceAgent(**_make_agent(slug="librarian", is_system=True))
    regular_agent = MarketplaceAgent(**_make_agent(slug="tesslate-agent", is_system=False))

    async with maker() as s:
        s.add(system_agent)
        s.add(regular_agent)
        await s.flush()

        for agent in (system_agent, regular_agent):
            s.add(
                UserPurchasedAgent(
                    id=uuid.uuid4(),
                    user_id=fake_user_id,
                    agent_id=agent.id,
                    purchase_type="free",
                    is_active=True,
                    purchase_date=_NOW,
                )
            )

        await s.commit()
        return system_agent.id, regular_agent.id


def test_my_agents_excludes_system_agents(db_setup) -> None:
    """GET /my-agents must not return is_system=True agents."""
    app, maker, _engine, fake_user = db_setup
    asyncio.run(_seed(maker, fake_user.id))

    with TestClient(app) as client:
        resp = client.get("/api/marketplace/my-agents")

    assert resp.status_code == 200
    slugs = {a["slug"] for a in resp.json()["agents"]}
    assert "tesslate-agent" in slugs
    assert "librarian" not in slugs


def test_browse_agents_excludes_system_agents(db_setup) -> None:
    """GET /agents browse must not return is_system=True agents."""
    app, maker, _engine, fake_user = db_setup
    asyncio.run(_seed(maker, fake_user.id))

    with TestClient(app) as client:
        resp = client.get("/api/marketplace/agents")

    assert resp.status_code == 200
    body = resp.json()
    # response is paginated: {"agents": [...], "total": ..., ...} or similar
    agents = body.get("agents", body.get("items", []))
    slugs = {a["slug"] for a in agents}
    assert "tesslate-agent" in slugs
    assert "librarian" not in slugs


def test_is_system_false_by_default(db_setup) -> None:
    """Agents without an explicit is_system value default to False."""
    from app.models import MarketplaceAgent

    app, maker, _engine, _user = db_setup

    async def _check():
        data = _make_agent(slug="default-agent")
        data.pop("is_system")  # omit the field
        async with maker() as s:
            agent = MarketplaceAgent(**data)
            s.add(agent)
            await s.commit()
            await s.refresh(agent)
            return agent.is_system

    result = asyncio.run(_check())
    assert result is False


def _load_marketplace_agent_seeds() -> list[dict]:
    """Read the canonical agent seed list from the federated marketplace.

    After Wave 10 the orchestrator no longer carries seed Python modules;
    catalog content lives in
    ``packages/tesslate-marketplace/app/seeds/agents.json`` and arrives via
    the federation sync worker. The contract these tests guard (system
    flag set on Librarian and only Librarian) is enforced upstream now.
    """
    import json
    from pathlib import Path

    seed_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "tesslate-marketplace"
        / "app"
        / "seeds"
        / "agents.json"
    )
    return json.loads(seed_path.read_text(encoding="utf-8"))


def test_seed_sets_is_system_on_librarian() -> None:
    """The Librarian entry in the marketplace seed has is_system=True."""
    agents = _load_marketplace_agent_seeds()

    librarian = next((a for a in agents if a["slug"] == "librarian"), None)
    assert librarian is not None, "Librarian agent not found in marketplace agents.json"
    assert librarian.get("is_system") is True


def test_regular_agents_in_seed_have_no_is_system_flag() -> None:
    """Non-system agents in the marketplace seed must not set is_system=True."""
    agents = _load_marketplace_agent_seeds()

    violations = [
        a["slug"] for a in agents if a.get("is_system") and a["slug"] != "librarian"
    ]
    assert violations == [], f"Unexpected is_system=True on: {violations}"
