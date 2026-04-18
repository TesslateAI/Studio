"""Unit tests for the built-in skill branch of ``discover_skills``.

Built-ins must appear in the catalog for **any** agent regardless of
``AgentSkillAssignment`` state, be flagged ``is_builtin=True`` on the
returned ``SkillCatalogEntry``, and de-dup cleanly against user-installed
duplicates.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

from app.services.skill_discovery import (
    SkillCatalogEntry,
    _discover_builtin_skills,
    discover_skills,
)


def _row(id_, name, description):
    r = MagicMock()
    r.id = id_
    r.name = name
    r.description = description
    return r


def _execute_result(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


class TestDiscoverBuiltinSkills:
    @pytest.mark.asyncio
    async def test_returns_builtin_entries_with_flag(self):
        pa_id = uuid4()
        rows = [_row(pa_id, "Project Architecture", "Full config reference")]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_execute_result(rows))

        skills = await _discover_builtin_skills(db)
        assert len(skills) == 1
        assert skills[0].name == "Project Architecture"
        assert skills[0].source == "builtin"
        assert skills[0].is_builtin is True
        assert skills[0].skill_id == pa_id

    @pytest.mark.asyncio
    async def test_empty_when_no_rows(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_execute_result([]))
        skills = await _discover_builtin_skills(db)
        assert skills == []

    @pytest.mark.asyncio
    async def test_db_failure_returns_empty_not_raise(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db down"))
        skills = await _discover_builtin_skills(db)
        assert skills == []


class TestDiscoverSkillsMerge:
    @pytest.mark.asyncio
    async def test_builtin_present_even_without_agent_id(self):
        """Built-ins appear for agents that have never installed a skill."""
        pa_id = uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_execute_result(
                [_row(pa_id, "Project Architecture", "ref")]
            )
        )

        skills = await discover_skills(
            agent_id=None,
            user_id=uuid4(),
            project_id=None,
            container_name=None,
            db=db,
        )
        assert any(s.source == "builtin" for s in skills)

    @pytest.mark.asyncio
    async def test_dedupe_against_user_assignment_with_same_skill_id(self):
        """A user who installed a built-in appears once, tagged as built-in."""
        pa_id = uuid4()
        agent_id = uuid4()
        user_id = uuid4()

        # First execute() call → built-in query. Second → DB (assigned) query.
        builtin_rows = [_row(pa_id, "Project Architecture", "ref")]
        assigned_rows = [_row(pa_id, "Project Architecture", "ref")]

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _execute_result(builtin_rows),
                _execute_result(assigned_rows),
            ]
        )

        skills = await discover_skills(
            agent_id=agent_id,
            user_id=user_id,
            project_id=None,
            container_name=None,
            db=db,
        )
        matches = [s for s in skills if s.skill_id == pa_id]
        assert len(matches) == 1
        assert matches[0].source == "builtin"
        assert matches[0].is_builtin is True

    @pytest.mark.asyncio
    async def test_assigned_only_skill_still_shows(self):
        """Non-built-in assigned skills aren't dropped by dedupe."""
        other_id = uuid4()
        agent_id = uuid4()
        user_id = uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _execute_result([]),  # built-ins: none
                _execute_result([_row(other_id, "My Custom Skill", "user skill")]),
            ]
        )

        skills = await discover_skills(
            agent_id=agent_id,
            user_id=user_id,
            project_id=None,
            container_name=None,
            db=db,
        )
        assert len(skills) == 1
        assert skills[0].source == "db"
        assert skills[0].skill_id == other_id


class TestSkillCatalogEntry:
    def test_default_is_builtin_false(self):
        entry = SkillCatalogEntry(name="x", description="y", source="db")
        assert entry.is_builtin is False

    def test_builtin_entry(self):
        entry = SkillCatalogEntry(
            name="Project Architecture",
            description="",
            source="builtin",
            is_builtin=True,
        )
        assert entry.is_builtin is True
