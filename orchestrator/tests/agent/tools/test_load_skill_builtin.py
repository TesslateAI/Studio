"""Unit tests for load_skill built-in fallback + marker rendering.

When the agent calls ``load_skill`` on a built-in skill (``source='builtin'``),
the body must be fetched from the DB by ID and run through the marker
renderer so live schema/catalog/rules are substituted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

from app.agent.tools.skill_ops.load_skill import load_skill_executor
from app.services.skill_discovery import SkillCatalogEntry
from app.services.skill_markers import _reset_cache_for_tests


@pytest.fixture(autouse=True)
def _clear_cache():
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


def _builtin_entry(skill_id=None):
    return SkillCatalogEntry(
        name="Project Architecture",
        description="Full config reference",
        source="builtin",
        skill_id=skill_id or uuid4(),
        is_builtin=True,
    )


@pytest.mark.asyncio
async def test_load_builtin_fetches_from_db_and_renders_markers():
    """A built-in skill's body runs through the marker renderer."""
    entry = _builtin_entry()
    raw_body = "# Doc\n\n{{TESSLATE_CONFIG_SCHEMA}}\n\n{{LIFECYCLE_TOOLS}}"

    db = AsyncMock()
    # load_skill queries MarketplaceAgent.skill_body by id
    scalar_result = Mock()
    scalar_result.scalar_one_or_none.return_value = raw_body
    db.execute = AsyncMock(return_value=scalar_result)

    context = {
        "available_skills": [entry],
        "db": db,
        "user_id": uuid4(),
        "project_id": "proj-123",
    }

    result = await load_skill_executor({"skill_name": "Project Architecture"}, context)

    assert result["success"] is True
    body = result["instructions"]
    # Markers were substituted — the literal placeholder is gone.
    assert "{{TESSLATE_CONFIG_SCHEMA}}" not in body
    assert "{{LIFECYCLE_TOOLS}}" not in body
    # Concrete content from the live renderers.
    assert "apps" in body  # from Pydantic schema
    assert "apply_setup_config" in body  # from LIFECYCLE_TOOLS


@pytest.mark.asyncio
async def test_load_builtin_case_insensitive_match():
    entry = _builtin_entry()
    raw_body = "plain body no markers"

    db = AsyncMock()
    scalar_result = Mock()
    scalar_result.scalar_one_or_none.return_value = raw_body
    db.execute = AsyncMock(return_value=scalar_result)

    context = {
        "available_skills": [entry],
        "db": db,
        "user_id": uuid4(),
        "project_id": "proj-123",
    }

    # Input in lowercase with different capitalization
    result = await load_skill_executor(
        {"skill_name": "project architecture"}, context
    )
    assert result["success"] is True
    assert result["instructions"] == "plain body no markers"


@pytest.mark.asyncio
async def test_load_non_builtin_skips_marker_rendering():
    """Regular DB skills (source='db') should NOT run through markers."""
    entry = SkillCatalogEntry(
        name="My Custom Skill",
        description="user skill",
        source="db",
        skill_id=uuid4(),
        is_builtin=False,
    )
    raw_body = "some body with {{TESSLATE_CONFIG_SCHEMA}} left raw"

    db = AsyncMock()
    scalar_result = Mock()
    scalar_result.scalar_one_or_none.return_value = raw_body
    db.execute = AsyncMock(return_value=scalar_result)

    context = {
        "available_skills": [entry],
        "db": db,
        "user_id": uuid4(),
        "project_id": "proj-123",
    }

    result = await load_skill_executor({"skill_name": "My Custom Skill"}, context)
    assert result["success"] is True
    # Marker stays literal — we don't try to inject platform docs into user skills.
    assert "{{TESSLATE_CONFIG_SCHEMA}}" in result["instructions"]


@pytest.mark.asyncio
async def test_load_builtin_uses_cache_on_second_call():
    """Second call for the same built-in hits cache — renderers not re-run."""
    from app.services import skill_markers

    entry = _builtin_entry()
    raw_body = "body {{TESSLATE_CONFIG_SCHEMA}}"

    db = AsyncMock()
    scalar_result = Mock()
    scalar_result.scalar_one_or_none.return_value = raw_body
    db.execute = AsyncMock(return_value=scalar_result)

    context = {
        "available_skills": [entry],
        "db": db,
        "user_id": uuid4(),
        "project_id": "proj-123",
    }

    call_count = {"n": 0}

    def _count():
        call_count["n"] += 1
        return "RENDERED-SCHEMA"

    with patch.dict(
        skill_markers.MARKER_RENDERERS,
        {"{{TESSLATE_CONFIG_SCHEMA}}": _count},
    ):
        await load_skill_executor({"skill_name": "Project Architecture"}, context)
        await load_skill_executor({"skill_name": "Project Architecture"}, context)
        await load_skill_executor({"skill_name": "Project Architecture"}, context)

    assert call_count["n"] == 1
