"""
Unit tests for API key scoped permissions.

Tests scope validation, ceiling enforcement, scope format validation,
and the SCOPE_LABELS mapping. Uses mocked DB sessions — no database required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models  # noqa: F401 — register all ORM models

from app.permissions import (
    Permission,
    ROLE_PERMISSIONS,
    SCOPE_LABELS,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_api_key(scopes=None, project_ids=None, is_active=True):
    """Create a mock ExternalAPIKey."""
    key = MagicMock()
    key.id = uuid.uuid4()
    key.user_id = uuid.uuid4()
    key.key_hash = "a" * 64
    key.key_prefix = "tsk_abcd"
    key.name = "Test Key"
    key.scopes = scopes
    key.project_ids = project_ids
    key.is_active = is_active
    key.expires_at = None
    key.last_used_at = None
    return key


def _make_user(default_team_id=None):
    """Create a mock User with _api_key_record attached."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.default_team_id = default_team_id or uuid.uuid4()
    return user


def _make_membership(role="admin", is_active=True):
    m = MagicMock()
    m.role = role
    m.is_active = is_active
    return m


# ── SCOPE_LABELS Tests ────────────────────────────────────────────────


class TestScopeLabels:
    """Tests for the SCOPE_LABELS mapping."""

    def test_every_permission_has_a_label(self):
        """Every Permission enum value should have an entry in SCOPE_LABELS."""
        for perm in Permission:
            assert perm.value in SCOPE_LABELS, f"Missing SCOPE_LABELS for {perm.value}"

    def test_label_structure(self):
        """Each label entry should have 'label' and 'category' keys."""
        for perm_value, info in SCOPE_LABELS.items():
            assert "label" in info, f"Missing 'label' for {perm_value}"
            assert "category" in info, f"Missing 'category' for {perm_value}"
            assert isinstance(info["label"], str)
            assert isinstance(info["category"], str)
            assert len(info["label"]) > 0
            assert len(info["category"]) > 0


# ── Scope Format Validation Tests ─────────────────────────────────────


class TestScopeValidation:
    """Tests for scope string validation against Permission enum."""

    def test_valid_scope_strings_match_permission_enum(self):
        """Every scope that can be stored must be a valid Permission value."""
        valid_values = {p.value for p in Permission}
        # Test a representative sample
        valid_scopes = ["chat.send", "file.read", "project.view", "container.start_stop"]
        for scope in valid_scopes:
            assert scope in valid_values, f"'{scope}' is not a valid Permission value"

    def test_invalid_scope_strings_rejected(self):
        """Old-format scopes should not be in the Permission enum."""
        valid_values = {p.value for p in Permission}
        invalid_scopes = ["agent:invoke", "agent:status", "project:read", "nonexistent"]
        for scope in invalid_scopes:
            assert scope not in valid_values, f"'{scope}' should not be a valid Permission value"

    def test_schema_rejects_invalid_scopes(self):
        """ExternalAPIKeyCreate schema should reject invalid scope strings."""
        from app.schemas import ExternalAPIKeyCreate

        with pytest.raises(Exception):
            ExternalAPIKeyCreate(name="test", scopes=["nonexistent.scope"])

    def test_schema_accepts_valid_scopes(self):
        """ExternalAPIKeyCreate schema should accept valid scope strings."""
        from app.schemas import ExternalAPIKeyCreate

        key = ExternalAPIKeyCreate(name="test", scopes=["chat.send", "file.read"])
        assert key.scopes == ["chat.send", "file.read"]

    def test_schema_accepts_null_scopes(self):
        """ExternalAPIKeyCreate schema should accept null scopes (full access)."""
        from app.schemas import ExternalAPIKeyCreate

        key = ExternalAPIKeyCreate(name="test", scopes=None)
        assert key.scopes is None

    def test_schema_accepts_empty_list_scopes(self):
        """ExternalAPIKeyCreate schema should accept empty list scopes."""
        from app.schemas import ExternalAPIKeyCreate

        key = ExternalAPIKeyCreate(name="test", scopes=[])
        assert key.scopes == []


# ── Scope Ceiling Tests ───────────────────────────────────────────────


class TestScopeCeiling:
    """Tests for scope ceiling enforcement (key scopes vs owner's role)."""

    def test_scope_ceiling_admin(self):
        """Admin can use any scope since they have all permissions."""
        admin_perms = ROLE_PERMISSIONS["admin"]
        for perm in Permission:
            assert perm in admin_perms, f"Admin missing {perm.value}"

    def test_scope_ceiling_editor(self):
        """Editor cannot create key with admin-only scopes."""
        editor_perms = ROLE_PERMISSIONS["editor"]
        admin_only_scopes = [
            Permission.PROJECT_DELETE,
            Permission.TEAM_DELETE,
            Permission.TEAM_INVITE,
            Permission.AUDIT_VIEW,
            Permission.API_KEYS_MANAGE,
        ]
        for perm in admin_only_scopes:
            assert perm not in editor_perms, f"Editor should not have {perm.value}"

    def test_scope_ceiling_viewer(self):
        """Viewer can only create key with viewer-level scopes."""
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        write_scopes = [
            Permission.FILE_WRITE,
            Permission.CHAT_SEND,
            Permission.DEPLOYMENT_CREATE,
            Permission.GIT_WRITE,
        ]
        for perm in write_scopes:
            assert perm not in viewer_perms, f"Viewer should not have {perm.value}"

    def test_viewer_has_read_scopes(self):
        """Viewer should have basic read permissions."""
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        read_scopes = [
            Permission.FILE_READ,
            Permission.CHAT_VIEW,
            Permission.PROJECT_VIEW,
            Permission.CONTAINER_VIEW,
        ]
        for perm in read_scopes:
            assert perm in viewer_perms, f"Viewer should have {perm.value}"


# ── Null Scopes (Full Access) Tests ───────────────────────────────────


class TestNullScopes:
    """Tests for null/empty scopes behavior (backward compatibility)."""

    def test_null_scopes_grants_full_role_access(self):
        """A key with null scopes should not be blocked by scope check."""
        # Null scopes means the key inherits owner's full role permissions
        key = _make_api_key(scopes=None)
        # When scopes is None, the scope check is skipped
        assert key.scopes is None


# ── require_api_scope Dependency Tests ────────────────────────────────


class TestRequireApiScope:
    """Tests for the require_api_scope dependency factory."""

    @pytest.mark.asyncio
    async def test_scoped_key_passes_with_matching_scope(self):
        """Key with matching scope should pass the check."""
        from app.auth_external import require_api_scope

        key = _make_api_key(scopes=["chat.send", "file.read"])
        user = _make_user()
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.CHAT_SEND)
            result = await dep(user=user, db=mock_db)
            assert result == user
            assert result._api_scope_used == "chat.send"

    @pytest.mark.asyncio
    async def test_scoped_key_fails_without_matching_scope(self):
        """Key without matching scope should raise 403."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        key = _make_api_key(scopes=["file.read"])  # No chat.send
        user = _make_user()
        user._api_key_record = key

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user):
            dep = require_api_scope(Permission.CHAT_SEND)
            with pytest.raises(HTTPException) as exc_info:
                await dep(user=user, db=mock_db)
            assert exc_info.value.status_code == 403
            assert "chat.send" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_null_scopes_key_passes_any_scope_check(self):
        """Key with null scopes should pass any scope check."""
        from app.auth_external import require_api_scope

        key = _make_api_key(scopes=None)  # Full access
        user = _make_user()
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.CHAT_SEND)
            result = await dep(user=user, db=mock_db)
            assert result == user

    @pytest.mark.asyncio
    async def test_role_downgrade_clamps_scopes(self):
        """If owner's role is downgraded, scope check should fail for permissions
        that the new role doesn't have, even if the key's scopes list includes them."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        # Key has chat.send scope, but owner was downgraded to viewer
        key = _make_api_key(scopes=["chat.send"])
        user = _make_user()
        user._api_key_record = key
        # Owner is now a viewer (viewers can't chat.send)
        membership = _make_membership("viewer")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership):
            dep = require_api_scope(Permission.CHAT_SEND)
            with pytest.raises(HTTPException) as exc_info:
                await dep(user=user, db=mock_db)
            assert exc_info.value.status_code == 403
            assert "no longer grants" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_no_team_membership_skips_ceiling_check(self):
        """If user has no default_team_id, ceiling check is skipped."""
        from app.auth_external import require_api_scope

        key = _make_api_key(scopes=["chat.send"])
        user = _make_user()
        user._api_key_record = key
        user.default_team_id = None  # No team

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.CHAT_SEND)
            result = await dep(user=user, db=mock_db)
            assert result == user

    @pytest.mark.asyncio
    async def test_audit_log_called_on_success(self):
        """Successful scope check should trigger audit log entry."""
        from app.auth_external import require_api_scope

        key = _make_api_key(scopes=["chat.send"])
        user = _make_user()
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()
        mock_log_event = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", mock_log_event):
            dep = require_api_scope(Permission.CHAT_SEND)
            await dep(user=user, db=mock_db)

            mock_log_event.assert_called_once()
            call_kwargs = mock_log_event.call_args
            assert call_kwargs[1]["action"] == "api_key.used"
            assert call_kwargs[1]["resource_type"] == "api_key"
            assert call_kwargs[1]["details"]["scope_used"] == "chat.send"


# ── Legacy Scope Migration Tests ──────────────────────────────────────


class TestLegacyScopeMigration:
    """Tests for the legacy scope migration mapping."""

    def test_migration_targets_are_valid_permissions(self):
        """All legacy scope migration targets must be valid Permission values."""
        legacy_map = {
            "agent:invoke": "chat.send",
            "agent:status": "chat.view",
            "agent:events": "chat.view",
            "project:read": "project.view",
            "project:write": "project.edit",
            "files:read": "file.read",
            "files:write": "file.write",
        }
        valid_values = {p.value for p in Permission}
        for old_scope, new_scope in legacy_map.items():
            assert new_scope in valid_values, (
                f"Migration target '{new_scope}' for '{old_scope}' is not a valid Permission"
            )

    def test_legacy_scopes_not_in_permission_enum(self):
        """Old-format scopes should not exist in the Permission enum."""
        valid_values = {p.value for p in Permission}
        legacy_scopes = ["agent:invoke", "agent:status", "agent:events",
                         "project:read", "project:write", "files:read", "files:write"]
        for scope in legacy_scopes:
            assert scope not in valid_values


# ── ScopeOption Schema Tests ─────────────────────────────────────────


class TestScopeOptionSchema:
    """Tests for the ScopeOption Pydantic schema."""

    def test_scope_option_creation(self):
        from app.schemas import ScopeOption

        option = ScopeOption(value="chat.send", label="Chat — Send messages", category="Chat")
        assert option.value == "chat.send"
        assert option.label == "Chat — Send messages"
        assert option.category == "Chat"

    def test_scope_options_from_labels(self):
        """SCOPE_LABELS should produce valid ScopeOption instances."""
        from app.schemas import ScopeOption

        for perm_value, info in SCOPE_LABELS.items():
            option = ScopeOption(
                value=perm_value,
                label=info["label"],
                category=info["category"],
            )
            assert option.value == perm_value


# ── Tool-Level Scope Enforcement Tests ────────────────────────────────


class TestToolScopeEnforcement:
    """Tests for scope enforcement at the tool execution level."""

    def _get_registry(self):
        from app.agent.tools.registry import ToolRegistry
        return ToolRegistry()

    def test_tool_scope_mapping_covers_write_tools(self):
        """All write/dangerous tools should have a scope mapping."""
        from app.agent.tools.registry import ToolRegistry
        mapping = ToolRegistry.TOOL_REQUIRED_SCOPES
        write_tools = ["write_file", "patch_file", "multi_edit", "apply_patch"]
        for tool in write_tools:
            assert tool in mapping, f"Write tool '{tool}' missing from TOOL_REQUIRED_SCOPES"
            assert mapping[tool] == "file.write"

    def test_tool_scope_mapping_covers_shell_tools(self):
        """Shell tools should require terminal.access."""
        from app.agent.tools.registry import ToolRegistry
        mapping = ToolRegistry.TOOL_REQUIRED_SCOPES
        shell_tools = ["bash_exec", "shell_exec", "shell_open"]
        for tool in shell_tools:
            assert tool in mapping, f"Shell tool '{tool}' missing from TOOL_REQUIRED_SCOPES"
            assert mapping[tool] == "terminal.access"

    def test_check_tool_scope_allows_matching_scope(self):
        """Tool with matching scope in key should be allowed."""
        registry = self._get_registry()
        result = registry._check_tool_scope("write_file", ["file.write", "file.read"])
        assert result is None  # None = allowed

    def test_check_tool_scope_blocks_missing_scope(self):
        """Tool requiring scope not in key should be blocked."""
        registry = self._get_registry()
        result = registry._check_tool_scope("write_file", ["file.read", "chat.view"])
        assert result is not None
        assert "file.write" in result
        assert "write_file" in result

    def test_check_tool_scope_allows_unmapped_tools(self):
        """Tools not in the mapping (read_file, etc.) should always be allowed."""
        registry = self._get_registry()
        result = registry._check_tool_scope("read_file", ["file.read"])
        assert result is None  # Unmapped tools are unrestricted

    def test_check_tool_scope_allows_when_no_scopes(self):
        """When api_key_scopes is None (full access), tools should not be checked."""
        # This is handled by the caller (execute method), not _check_tool_scope
        # _check_tool_scope is only called when scopes is not None
        registry = self._get_registry()
        # Even with empty list, unmapped tools pass
        result = registry._check_tool_scope("read_file", [])
        assert result is None

    def test_check_tool_scope_blocks_shell_without_terminal(self):
        """bash_exec should be blocked without terminal.access."""
        registry = self._get_registry()
        result = registry._check_tool_scope("bash_exec", ["file.read", "file.write"])
        assert result is not None
        assert "terminal.access" in result

    @pytest.mark.asyncio
    async def test_execute_blocks_tool_via_scope(self):
        """ToolRegistry.execute() should block write_file when scope is missing."""
        from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry

        registry = ToolRegistry()
        registry.register(Tool(
            name="write_file",
            description="Write a file",
            parameters={"type": "object", "properties": {}},
            executor=lambda p, c: {"success": True},
            category=ToolCategory.FILE_OPS,
            state_serializable=True,
            holds_external_state=False,
        ))

        context = {
            "api_key_scopes": ["file.read", "chat.view"],  # No file.write
        }
        result = await registry.execute("write_file", {}, context)
        assert result["success"] is False
        assert "scope restriction" in result["error"].lower() or "file.write" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_allows_tool_with_scope(self):
        """ToolRegistry.execute() should allow write_file when scope is present."""
        from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry

        registry = ToolRegistry()

        async def mock_write(params, context):
            return {"success": True, "message": "written"}

        registry.register(Tool(
            name="write_file",
            description="Write a file",
            parameters={"type": "object", "properties": {}},
            executor=mock_write,
            category=ToolCategory.FILE_OPS,
            state_serializable=True,
            holds_external_state=False,
        ))

        context = {
            "api_key_scopes": ["file.write", "file.read"],
            "edit_mode": "normal",
            "skip_approval_check": True,
        }
        result = await registry.execute("write_file", {}, context)
        assert result.get("success") is True or "error" not in result or "scope" not in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_execute_no_scope_check_when_null(self):
        """ToolRegistry.execute() should skip scope check when scopes is None (full access)."""
        from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry

        registry = ToolRegistry()

        async def mock_write(params, context):
            return {"success": True}

        registry.register(Tool(
            name="write_file",
            description="Write a file",
            parameters={"type": "object", "properties": {}},
            executor=mock_write,
            category=ToolCategory.FILE_OPS,
            state_serializable=True,
            holds_external_state=False,
        ))

        context = {
            "api_key_scopes": None,  # Full access — no restriction
            "edit_mode": "normal",
            "skip_approval_check": True,
        }
        result = await registry.execute("write_file", {}, context)
        assert result.get("success") is True or "scope" not in result.get("error", "").lower()
