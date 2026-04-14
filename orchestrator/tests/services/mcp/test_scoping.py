"""Unit tests for :mod:`app.services.mcp.scoping`.

Exercises the precedence logic (`_apply_precedence`) directly without a real
DB so tests are fast and self-contained. Full-stack resolution is covered by
the integration suite.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.mcp.scoping import _apply_precedence


pytestmark = pytest.mark.unit


def _row(*, scope_level: str, marketplace_agent_id=None):
    return SimpleNamespace(
        scope_level=scope_level,
        marketplace_agent_id=marketplace_agent_id,
    )


def test_project_beats_user_beats_team_for_same_agent():
    agent_id = uuid4()
    team_row = _row(scope_level="team", marketplace_agent_id=agent_id)
    user_row = _row(scope_level="user", marketplace_agent_id=agent_id)
    project_row = _row(scope_level="project", marketplace_agent_id=agent_id)

    out = _apply_precedence([team_row, user_row, project_row])
    assert out == [project_row]


def test_user_beats_team_when_no_project_row():
    agent_id = uuid4()
    out = _apply_precedence(
        [
            _row(scope_level="team", marketplace_agent_id=agent_id),
            u := _row(scope_level="user", marketplace_agent_id=agent_id),
        ]
    )
    assert out == [u]


def test_different_agents_never_collide():
    a, b = uuid4(), uuid4()
    ra = _row(scope_level="team", marketplace_agent_id=a)
    rb = _row(scope_level="user", marketplace_agent_id=b)
    out = _apply_precedence([ra, rb])
    # Order within the dict is insertion order; exact order doesn't matter.
    assert set(out) == {ra, rb}


def test_custom_connectors_never_dedupe():
    # Two custom connectors (marketplace_agent_id is None) must both survive.
    c1 = _row(scope_level="user", marketplace_agent_id=None)
    c2 = _row(scope_level="team", marketplace_agent_id=None)
    c3 = _row(scope_level="project", marketplace_agent_id=None)
    out = _apply_precedence([c1, c2, c3])
    # Custom rows are appended to the end and preserved.
    assert len([r for r in out if r.marketplace_agent_id is None]) == 3


def test_mix_of_catalog_and_custom():
    agent_id = uuid4()
    cat_team = _row(scope_level="team", marketplace_agent_id=agent_id)
    cat_project = _row(scope_level="project", marketplace_agent_id=agent_id)
    custom = _row(scope_level="user", marketplace_agent_id=None)

    out = _apply_precedence([cat_team, custom, cat_project])
    # Catalog: project wins over team. Custom: always kept.
    assert cat_project in out
    assert cat_team not in out
    assert custom in out
    assert len(out) == 2
