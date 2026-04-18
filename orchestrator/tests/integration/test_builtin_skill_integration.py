"""End-to-end check: a freshly-registered user's agent sees the built-in
skill in its catalog, can load its body via the ``load_skill`` tool
equivalent path, and the body has every marker substituted with live
content from the Python code.

The orchestrator seed runs automatically on startup (background task), but
in the isolated test DB it may not have executed yet. We therefore upsert
the seed's canonical ``project-architecture`` row synchronously at the top
of each test, matching the seed's fields 1:1 including ``is_builtin=True``.
Then we exercise ``discover_skills`` + ``load_skill`` against it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import MarketplaceAgent

_ASYNC_DB_URL = "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test"


def _run_db(coro_fn, *args, **kwargs):
    async def _inner():
        engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _upsert_project_architecture_builtin() -> str:
    """Upsert the canonical built-in skill the way seeds/skills.py does."""
    from app.seeds.skills import TESSLATE_SKILLS

    pa = next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")

    async def _do(db: AsyncSession) -> str:
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == pa["slug"])
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = MarketplaceAgent(
                name=pa["name"],
                slug=pa["slug"],
                description=pa["description"],
                long_description=pa.get("long_description"),
                category=pa["category"],
                item_type=pa["item_type"],
                pricing_type=pa["pricing_type"],
                price=pa["price"],
                is_active=pa["is_active"],
                is_published=pa["is_published"],
                is_forkable=pa.get("is_forkable", False),
                is_featured=pa.get("is_featured", False),
                is_builtin=pa["is_builtin"],
                skill_body=pa["skill_body"],
                icon=pa.get("icon"),
                tags=pa.get("tags"),
                features=pa.get("features"),
                created_by_user_id=None,
            )
            db.add(row)
        else:
            row.skill_body = pa["skill_body"]
            row.is_builtin = True
            row.is_active = True
            row.description = pa["description"]
        await db.commit()
        await db.refresh(row)
        return str(row.id)

    return _run_db(_do)


@pytest.mark.integration
def test_builtin_discovered_for_any_agent():
    """``discover_skills`` returns the built-in even with no AgentSkillAssignment."""
    _upsert_project_architecture_builtin()

    async def _do(db: AsyncSession):
        from app.services.skill_discovery import discover_skills

        return await discover_skills(
            agent_id=uuid.uuid4(),  # agent that has no assignments
            user_id=uuid.uuid4(),
            project_id=None,
            container_name=None,
            db=db,
        )

    skills = _run_db(_do)
    names = [s.name for s in skills]
    assert "Project Architecture" in names
    pa = next(s for s in skills if s.name == "Project Architecture")
    assert pa.source == "builtin"
    assert pa.is_builtin is True


@pytest.mark.integration
def test_load_skill_returns_rendered_body():
    """Loading the built-in returns a body with every marker substituted."""
    _upsert_project_architecture_builtin()

    # Use the real load_skill executor path via the public service layer.
    from app.agent.tools.skill_ops.load_skill import load_skill_executor
    from app.services import skill_markers
    from app.services.skill_discovery import SkillCatalogEntry

    skill_markers._reset_cache_for_tests()

    # Fetch the real skill ID for the built-in.
    async def _get_id(db: AsyncSession) -> str:
        result = await db.execute(
            select(MarketplaceAgent.id).where(
                MarketplaceAgent.slug == "project-architecture"
            )
        )
        return str(result.scalar_one())

    skill_id = _run_db(_get_id)

    entry = SkillCatalogEntry(
        name="Project Architecture",
        description="ref",
        source="builtin",
        skill_id=uuid.UUID(skill_id),
        is_builtin=True,
    )

    async def _run_tool(db: AsyncSession):
        context = {
            "available_skills": [entry],
            "db": db,
            "user_id": uuid.uuid4(),
            "project_id": "proj-test",
        }
        return await load_skill_executor(
            {"skill_name": "Project Architecture"}, context
        )

    result = _run_db(_run_tool)
    assert result["success"] is True
    body = result["instructions"]

    # Every marker resolved — nothing remains literal.
    import re

    assert not re.findall(r"\{\{[A-Z_]+\}\}", body), (
        "markers still present after load"
    )

    # Concrete content from each renderer.
    assert "apps" in body  # TesslateConfigCreate schema
    assert "primaryApp" in body  # TesslateConfigCreate schema
    assert "postgres" in body.lower()  # service catalog
    assert "Vercel" in body  # deployment compatibility
    assert "apply_setup_config" in body  # lifecycle tools
    assert "0.0.0.0" in body  # startup rules
    assert "from_node" in body  # connection semantics
