"""
Unit tests for the RBAC permission system.

Tests dual-scope access resolution, role permissions, permission boundaries,
and edge cases. Uses mocked DB sessions — no database required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models  # noqa: F401 — register all ORM models so mapper resolves cross-module relationships

from app.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    get_effective_project_role,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_project(team_id=None, visibility="team", owner_id=None):
    project = MagicMock()
    project.id = uuid.uuid4()
    project.slug = "test-project"
    project.team_id = team_id or uuid.uuid4()
    project.visibility = visibility
    project.owner_id = owner_id or uuid.uuid4()
    return project


def _make_membership(role, is_active=True):
    m = MagicMock()
    m.role = role
    m.is_active = is_active
    return m


def _make_user_row(is_superuser=False):
    u = MagicMock()
    u.is_superuser = is_superuser
    return u


def _setup_db_for_role_test(
    is_superuser=False,
    team_membership=None,
    project_membership=None,
):
    """Create a mock db that returns the right things for get_effective_project_role.

    The function makes 3 queries:
    1. select(User) — superuser check
    2. select(TeamMembership) via get_team_membership — team role
    3. select(ProjectMembership) — project override
    """
    db = AsyncMock()

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = _make_user_row(is_superuser)

    team_result = MagicMock()
    team_result.scalar_one_or_none.return_value = team_membership

    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = project_membership

    db.execute.side_effect = [user_result, team_result, project_result]
    return db


# ── Permission Enum Tests ───────────────────────────────────────────────


class TestPermissionEnum:
    def test_admin_has_all_permissions(self):
        assert ROLE_PERMISSIONS["admin"] == {p for p in Permission}

    def test_admin_count_matches_enum(self):
        assert len(ROLE_PERMISSIONS["admin"]) == len(Permission)

    def test_editor_subset_of_admin(self):
        assert ROLE_PERMISSIONS["editor"] < ROLE_PERMISSIONS["admin"]

    def test_viewer_subset_of_editor(self):
        assert ROLE_PERMISSIONS["viewer"] < ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_delete_team(self):
        assert Permission.TEAM_DELETE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_manage_billing(self):
        assert Permission.BILLING_MANAGE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_delete_projects(self):
        assert Permission.PROJECT_DELETE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_invite_members(self):
        assert Permission.TEAM_INVITE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_remove_members(self):
        assert Permission.TEAM_REMOVE_MEMBER not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_change_roles(self):
        assert Permission.TEAM_CHANGE_ROLE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_manage_api_keys(self):
        assert Permission.API_KEYS_MANAGE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_export_audit(self):
        assert Permission.AUDIT_EXPORT not in ROLE_PERMISSIONS["editor"]

    def test_editor_can_create_projects(self):
        assert Permission.PROJECT_CREATE in ROLE_PERMISSIONS["editor"]

    def test_editor_can_write_files(self):
        assert Permission.FILE_WRITE in ROLE_PERMISSIONS["editor"]

    def test_editor_can_send_chat(self):
        assert Permission.CHAT_SEND in ROLE_PERMISSIONS["editor"]

    def test_editor_can_create_deployments(self):
        assert Permission.DEPLOYMENT_CREATE in ROLE_PERMISSIONS["editor"]

    def test_editor_can_manage_containers(self):
        assert Permission.CONTAINER_CREATE in ROLE_PERMISSIONS["editor"]
        assert Permission.CONTAINER_EDIT in ROLE_PERMISSIONS["editor"]
        assert Permission.CONTAINER_START_STOP in ROLE_PERMISSIONS["editor"]

    def test_editor_can_access_terminal(self):
        assert Permission.TERMINAL_ACCESS in ROLE_PERMISSIONS["editor"]

    def test_viewer_can_read_files(self):
        assert Permission.FILE_READ in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_write_files(self):
        assert Permission.FILE_WRITE not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_send_chat(self):
        assert Permission.CHAT_SEND not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_create_projects(self):
        assert Permission.PROJECT_CREATE not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_access_terminal(self):
        assert Permission.TERMINAL_ACCESS not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_cannot_create_deployments(self):
        assert Permission.DEPLOYMENT_CREATE not in ROLE_PERMISSIONS["viewer"]

    def test_viewer_can_view_projects(self):
        assert Permission.PROJECT_VIEW in ROLE_PERMISSIONS["viewer"]

    def test_viewer_can_view_containers(self):
        assert Permission.CONTAINER_VIEW in ROLE_PERMISSIONS["viewer"]

    def test_viewer_can_view_deployments(self):
        assert Permission.DEPLOYMENT_VIEW in ROLE_PERMISSIONS["viewer"]

    def test_unknown_role_not_in_map(self):
        assert "unknown_role" not in ROLE_PERMISSIONS

    def test_all_three_roles_exist(self):
        assert set(ROLE_PERMISSIONS.keys()) == {"admin", "editor", "viewer"}

    def test_editor_cannot_delete_containers(self):
        assert Permission.CONTAINER_DELETE not in ROLE_PERMISSIONS["editor"]

    def test_editor_cannot_delete_deployments(self):
        assert Permission.DEPLOYMENT_DELETE not in ROLE_PERMISSIONS["editor"]


# ── Dual-Scope Access Resolution Tests ──────────────────────────────────


class TestDualScopeResolution:
    """Tests for get_effective_project_role dual-scope logic from PRD Section 2."""

    @pytest.mark.asyncio
    async def test_superuser_always_admin(self):
        """Superuser bypasses all checks."""
        db = _setup_db_for_role_test(is_superuser=True)
        project = _make_project()
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "admin"

    @pytest.mark.asyncio
    async def test_scenario_1_team_admin_always_gets_admin(self):
        """Team Admin opens any project -> Admin access."""
        db = _setup_db_for_role_test(
            team_membership=_make_membership("admin"),
        )
        project = _make_project()
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "admin"

    @pytest.mark.asyncio
    async def test_scenario_2_team_editor_no_project_override(self):
        """Team Editor, no project override -> Editor access."""
        db = _setup_db_for_role_test(
            team_membership=_make_membership("editor"),
            project_membership=None,
        )
        project = _make_project(visibility="team")
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_scenario_3_team_editor_restricted_to_viewer(self):
        """Team Editor, assigned Viewer on Project X -> Viewer."""
        db = _setup_db_for_role_test(
            team_membership=_make_membership("editor"),
            project_membership=_make_membership("viewer"),
        )
        project = _make_project()
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "viewer"

    @pytest.mark.asyncio
    async def test_scenario_4_team_viewer_elevated_to_editor(self):
        """Team Viewer, assigned Editor on Project Y -> Editor."""
        db = _setup_db_for_role_test(
            team_membership=_make_membership("viewer"),
            project_membership=_make_membership("editor"),
        )
        project = _make_project()
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_scenario_5_private_project_no_access(self):
        """Team Viewer, not assigned to private project -> None."""
        user_id = uuid.uuid4()
        db = _setup_db_for_role_test(
            team_membership=_make_membership("viewer"),
            project_membership=None,
        )
        # owner_id is different from user_id (no legacy compat)
        project = _make_project(visibility="private", owner_id=uuid.uuid4())
        role = await get_effective_project_role(db, project, user_id)
        assert role is None

    @pytest.mark.asyncio
    async def test_scenario_6_team_visible_project_fallback(self):
        """Team Viewer, not assigned to team-visible project -> Viewer."""
        db = _setup_db_for_role_test(
            team_membership=_make_membership("viewer"),
            project_membership=None,
        )
        project = _make_project(visibility="team")
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "viewer"

    @pytest.mark.asyncio
    async def test_external_collaborator_with_project_membership(self):
        """No team membership but has project membership -> uses project role."""
        db = _setup_db_for_role_test(
            team_membership=None,
            project_membership=_make_membership("editor"),
        )
        project = _make_project()
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "editor"

    @pytest.mark.asyncio
    async def test_no_team_no_project_no_access(self):
        """No team or project membership -> None (unless legacy owner)."""
        user_id = uuid.uuid4()
        db = _setup_db_for_role_test(
            team_membership=None,
            project_membership=None,
        )
        # owner_id is different from user_id
        project = _make_project(owner_id=uuid.uuid4())
        role = await get_effective_project_role(db, project, user_id)
        assert role is None

    @pytest.mark.asyncio
    async def test_legacy_owner_gets_admin_even_without_memberships(self):
        """Legacy: project.owner_id == user_id -> admin (backward compat)."""
        user_id = uuid.uuid4()
        db = _setup_db_for_role_test(
            team_membership=None,
            project_membership=None,
        )
        project = _make_project(owner_id=user_id)
        role = await get_effective_project_role(db, project, user_id)
        assert role == "admin"

    @pytest.mark.asyncio
    async def test_team_admin_sees_private_project(self):
        """Team Admin can access private projects without project membership."""
        db = _setup_db_for_role_test(
            team_membership=_make_membership("admin"),
        )
        project = _make_project(visibility="private")
        role = await get_effective_project_role(db, project, uuid.uuid4())
        assert role == "admin"


# ── Model Tests ─────────────────────────────────────────────────────────


class TestTeamModel:
    def test_team_table_name(self):
        from app.models_team import Team
        assert Team.__tablename__ == "teams"

    def test_team_has_billing_fields(self):
        from app.models_team import Team
        billing_fields = [
            "subscription_tier", "stripe_customer_id", "stripe_subscription_id",
            "total_spend", "bundled_credits", "purchased_credits", "daily_credits",
            "signup_bonus_credits", "signup_bonus_expires_at", "credits_reset_date",
            "daily_credits_reset_date", "support_tier", "deployed_projects_count",
        ]
        for field in billing_fields:
            assert hasattr(Team, field), f"Team missing billing field: {field}"


class TestMembershipModels:
    def test_team_membership_table(self):
        from app.models_team import TeamMembership
        assert TeamMembership.__tablename__ == "team_memberships"

    def test_project_membership_table(self):
        from app.models_team import ProjectMembership
        assert ProjectMembership.__tablename__ == "project_memberships"

    def test_invitation_table(self):
        from app.models_team import TeamInvitation
        assert TeamInvitation.__tablename__ == "team_invitations"

    def test_audit_log_table(self):
        from app.models_team import AuditLog
        assert AuditLog.__tablename__ == "audit_logs"


# ── Audit Service Tests ─────────────────────────────────────────────────


class TestAuditService:
    @pytest.mark.asyncio
    async def test_log_event_never_raises_on_error(self):
        """log_event should catch exceptions and not raise (non-blocking)."""
        from app.services.audit_service import log_event
        db = AsyncMock()
        db.add.side_effect = Exception("DB down")

        # Should NOT raise
        await log_event(
            db=db, team_id=uuid.uuid4(), user_id=uuid.uuid4(),
            action="test.action", resource_type="test",
        )

    @pytest.mark.asyncio
    async def test_cleanup_executes_delete(self):
        from app.services.audit_service import cleanup_expired_audit_logs
        db = AsyncMock()
        await cleanup_expired_audit_logs(db, retention_days=90)
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_never_raises(self):
        from app.services.audit_service import cleanup_expired_audit_logs
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")
        await cleanup_expired_audit_logs(db)


# ── Credit Service Tests ────────────────────────────────────────────────


class TestCreditServiceTeamBilling:
    @pytest.mark.asyncio
    async def test_check_credits_with_team(self):
        from app.services.credit_service import check_credits
        team = MagicMock()
        team.total_credits = 100
        user = MagicMock()
        ok, msg = await check_credits(user, "tesslate/default", team=team)
        assert ok is True
        assert msg == ""

    @pytest.mark.asyncio
    async def test_check_credits_team_no_credits(self):
        from app.services.credit_service import check_credits
        team = MagicMock()
        team.total_credits = 0
        user = MagicMock()
        ok, msg = await check_credits(user, "tesslate/default", team=team)
        assert ok is False
        assert "no credits" in msg.lower()

    @pytest.mark.asyncio
    async def test_check_credits_byok_always_passes(self):
        from app.services.credit_service import check_credits
        team = MagicMock()
        team.total_credits = 0
        user = MagicMock()
        ok, msg = await check_credits(user, "openai/gpt-4", team=team)
        assert ok is True

    def test_is_byok_model(self):
        from app.services.credit_service import is_byok_model
        assert is_byok_model("openai/gpt-4") is True
        assert is_byok_model("anthropic/claude-3") is True
        assert is_byok_model("tesslate/default") is False


# ── Schema Validation Tests ─────────────────────────────────────────────


class TestSchemaValidation:
    def test_team_create_valid(self):
        from app.schemas_team import TeamCreate
        tc = TeamCreate(name="My Team", slug="my-team")
        assert tc.name == "My Team"

    def test_team_create_rejects_empty_name(self):
        from app.schemas_team import TeamCreate
        with pytest.raises(Exception):
            TeamCreate(name="", slug="my-team")

    def test_team_create_rejects_invalid_slug(self):
        from app.schemas_team import TeamCreate
        with pytest.raises(Exception):
            TeamCreate(name="My Team", slug="INVALID SLUG!")

    def test_invite_email_valid(self):
        from app.schemas_team import InviteEmailRequest
        inv = InviteEmailRequest(email="test@example.com", role="editor")
        assert inv.role == "editor"

    def test_invite_email_rejects_invalid_role(self):
        from app.schemas_team import InviteEmailRequest
        with pytest.raises(Exception):
            InviteEmailRequest(email="test@example.com", role="superadmin")

    def test_member_update_valid_roles(self):
        from app.schemas_team import TeamMemberUpdate
        for role in ["admin", "editor", "viewer"]:
            tm = TeamMemberUpdate(role=role)
            assert tm.role == role

    def test_member_update_rejects_invalid_role(self):
        from app.schemas_team import TeamMemberUpdate
        with pytest.raises(Exception):
            TeamMemberUpdate(role="owner")

    def test_audit_log_filter_defaults(self):
        from app.schemas_team import AuditLogFilter
        f = AuditLogFilter()
        assert f.page == 1
        assert f.per_page == 50

    def test_project_member_add_valid(self):
        from app.schemas_team import ProjectMemberAdd
        pm = ProjectMemberAdd(user_id=uuid.uuid4(), role="editor")
        assert pm.role == "editor"

    def test_invite_link_request_defaults(self):
        from app.schemas_team import InviteLinkRequest
        ilr = InviteLinkRequest(role="viewer")
        assert ilr.expires_in_days == 30
        assert ilr.max_uses is None
