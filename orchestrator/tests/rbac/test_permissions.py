"""
Unit tests for the RBAC permission system.

Tests dual-scope access resolution, role permissions, and edge cases.
These tests use mocked DB sessions — no database required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    get_effective_project_role,
)


# ── Permission Enum Tests ───────────────────────────────────────────────


class TestPermissionEnum:
    def test_admin_has_all_permissions(self):
        """Admin role should have every permission."""
        assert ROLE_PERMISSIONS["admin"] == {p for p in Permission}

    def test_editor_cannot_delete_team(self):
        assert Permission.TEAM_DELETE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_manage_billing(self):
        assert Permission.BILLING_MANAGE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_delete_projects(self):
        assert Permission.PROJECT_DELETE not in ROLE_PERMISSIONS["editor"]

    def test_editor_can_create_projects(self):
        assert Permission.PROJECT_CREATE in ROLE_PERMISSIONS["editor"]

    def test_editor_can_write_files(self):
        assert Permission.FILE_WRITE in ROLE_PERMISSIONS["editor"]

    def test_editor_can_send_chat(self):
        assert Permission.CHAT_SEND in ROLE_PERMISSIONS["editor"]

    def test_viewer_can_read_files(self):
        assert Permission.FILE_READ in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_write_files(self):
        assert Permission.FILE_WRITE not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_send_chat(self):
        assert Permission.CHAT_SEND not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_create_projects(self):
        assert Permission.PROJECT_CREATE not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_can_view_projects(self):
        assert Permission.PROJECT_VIEW in ROLE_PERMISSIONS["viewer"]

    def test_unknown_role_has_no_permissions(self):
        assert "unknown_role" not in ROLE_PERMISSIONS


# ── Dual-Scope Access Resolution Tests ──────────────────────────────────


def _make_project(team_id=None, visibility="team", owner_id=None):
    project = MagicMock()
    project.id = uuid.uuid4()
    project.team_id = team_id or uuid.uuid4()
    project.visibility = visibility
    project.owner_id = owner_id or uuid.uuid4()
    return project


def _make_membership(role):
    m = MagicMock()
    m.role = role
    m.is_active = True
    return m


@pytest.mark.mocked
class TestDualScopeResolution:
    """Tests for get_effective_project_role dual-scope logic from PRD Section 2."""

    @pytest.mark.asyncio
    async def test_team_admin_always_gets_admin(self):
        """Scenario 1: Team Admin opens any project → Admin access."""
        db = AsyncMock()
        project = _make_project()
        user_id = uuid.uuid4()

        # Mock team membership as admin
        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = _make_membership("admin")
        db.execute.return_value = team_result

        role = await get_effective_project_role(db, project, user_id)
        assert role == "admin"

    @pytest.mark.asyncio
    async def test_team_editor_no_project_override(self):
        """Scenario 2: Team Editor, no project override → Editor access."""
        db = AsyncMock()
        project = _make_project(visibility="team")
        user_id = uuid.uuid4()

        # First call returns team membership (editor)
        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = _make_membership("editor")

        # Second call returns no project membership
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_team_editor_restricted_to_viewer_on_project(self):
        """Scenario 3: Team Editor, assigned Viewer on Project X → Viewer."""
        db = AsyncMock()
        project = _make_project()
        user_id = uuid.uuid4()

        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = _make_membership("editor")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = _make_membership("viewer")

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role == "viewer"

    @pytest.mark.asyncio
    async def test_team_viewer_elevated_to_editor_on_project(self):
        """Scenario 4: Team Viewer, assigned Editor on Project Y → Editor."""
        db = AsyncMock()
        project = _make_project()
        user_id = uuid.uuid4()

        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = _make_membership("viewer")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = _make_membership("editor")

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_team_viewer_no_access_to_private_project(self):
        """Scenario 5: Team Viewer, not assigned to private project → None."""
        db = AsyncMock()
        project = _make_project(visibility="private")
        user_id = uuid.uuid4()

        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = _make_membership("viewer")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role is None

    @pytest.mark.asyncio
    async def test_team_viewer_sees_team_visible_project(self):
        """Scenario 6: Team Viewer, not assigned to team-visible project → Viewer."""
        db = AsyncMock()
        project = _make_project(visibility="team")
        user_id = uuid.uuid4()

        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = _make_membership("viewer")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role == "viewer"

    @pytest.mark.asyncio
    async def test_no_team_membership_with_project_membership(self):
        """External collaborator: no team membership but has project membership."""
        db = AsyncMock()
        project = _make_project()
        user_id = uuid.uuid4()

        # No team membership
        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = None

        # Has project membership
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = _make_membership("editor")

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_no_team_no_project_membership(self):
        """No team or project membership → None (no access)."""
        db = AsyncMock()
        project = _make_project()
        user_id = uuid.uuid4()

        team_result = MagicMock()
        team_result.scalar_one_or_none.return_value = None

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [team_result, project_result]

        role = await get_effective_project_role(db, project, user_id)
        assert role is None
