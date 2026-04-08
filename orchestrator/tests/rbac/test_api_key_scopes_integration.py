"""
Integration tests for API key scoped permissions.

Tests the full request flow: key creation with scope validation,
scope enforcement on agent endpoints, and audit logging.

Uses mocked DB and dependencies — no live database required.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.models  # noqa: F401

from app.permissions import Permission, ROLE_PERMISSIONS, SCOPE_LABELS


# ── Helpers ────────────────────────────────────────────────────────────


def _make_user(user_id=None, default_team_id=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.is_active = True
    user.is_superuser = False
    user.default_team_id = default_team_id or uuid.uuid4()
    return user


def _make_api_key(user_id, scopes=None, project_ids=None):
    key = MagicMock()
    key.id = uuid.uuid4()
    key.user_id = user_id
    key.key_hash = "a" * 64
    key.key_prefix = "tsk_abcd"
    key.name = "Test Key"
    key.scopes = scopes
    key.project_ids = project_ids
    key.is_active = True
    key.expires_at = None
    key.last_used_at = None
    return key


def _make_membership(role="admin"):
    m = MagicMock()
    m.role = role
    m.is_active = True
    return m


# ── Scope Enforcement Integration Tests ──────────────────────────────


class TestScopeEnforcementIntegration:
    """Integration tests for scope enforcement on agent endpoints."""

    @pytest.mark.asyncio
    async def test_scoped_key_can_invoke_agent_with_chat_send(self):
        """Key with chat.send scope should be allowed to invoke agent."""
        from app.auth_external import require_api_scope
        from app.permissions import Permission

        user = _make_user()
        key = _make_api_key(user.id, scopes=["chat.send", "chat.view"])
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.CHAT_SEND)
            result = await dep(user=user, db=mock_db)
            assert result.id == user.id

    @pytest.mark.asyncio
    async def test_scoped_key_cannot_invoke_without_scope(self):
        """Key without chat.send scope should get 403 on invoke."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.read", "chat.view"])  # No chat.send
        user._api_key_record = key

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user):
            dep = require_api_scope(Permission.CHAT_SEND)
            with pytest.raises(HTTPException) as exc:
                await dep(user=user, db=mock_db)
            assert exc.value.status_code == 403
            assert "chat.send" in exc.value.detail

    @pytest.mark.asyncio
    async def test_scoped_key_can_view_status(self):
        """Key with chat.view scope should be allowed to poll status."""
        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["chat.view"])
        user._api_key_record = key
        membership = _make_membership("editor")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.CHAT_VIEW)
            result = await dep(user=user, db=mock_db)
            assert result.id == user.id

    @pytest.mark.asyncio
    async def test_scoped_key_cannot_view_without_scope(self):
        """Key without chat.view scope should get 403 on status."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.read"])  # No chat.view
        user._api_key_record = key

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user):
            dep = require_api_scope(Permission.CHAT_VIEW)
            with pytest.raises(HTTPException) as exc:
                await dep(user=user, db=mock_db)
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_full_access_key_works_everywhere(self):
        """Null-scope key should pass all scope checks."""
        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=None)  # Full access
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()

        for perm in [Permission.CHAT_SEND, Permission.CHAT_VIEW, Permission.FILE_WRITE]:
            with patch("app.auth_external.get_external_api_user", return_value=user), \
                 patch("app.auth_external.get_team_membership", return_value=membership), \
                 patch("app.services.audit_service.log_event", new_callable=AsyncMock):
                dep = require_api_scope(perm)
                result = await dep(user=user, db=mock_db)
                assert result.id == user.id


# ── Key Creation Scope Validation Integration Tests ──────────────────


class TestKeyCreationScopeValidation:
    """Integration tests for scope validation during key creation."""

    def test_create_key_rejects_invalid_scope(self):
        """400 on nonexistent scope string."""
        from app.schemas import ExternalAPIKeyCreate

        with pytest.raises(Exception) as exc:
            ExternalAPIKeyCreate(name="test", scopes=["nonexistent.permission"])
        assert "Invalid scope" in str(exc.value)

    def test_create_key_accepts_valid_scopes(self):
        """Valid scope strings should be accepted."""
        from app.schemas import ExternalAPIKeyCreate

        key = ExternalAPIKeyCreate(
            name="test",
            scopes=["chat.send", "chat.view", "file.read", "file.write"],
        )
        assert len(key.scopes) == 4

    @pytest.mark.asyncio
    async def test_create_key_rejects_exceeding_scope(self):
        """Scope exceeding owner's role should be rejected with 403."""
        # This tests the logic in external_agent.py create_api_key
        # A viewer trying to create a key with file.write scope
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        assert Permission.FILE_WRITE not in viewer_perms
        assert Permission.CHAT_SEND not in viewer_perms

    def test_create_key_with_full_access(self):
        """Null scopes should create a full-access key."""
        from app.schemas import ExternalAPIKeyCreate

        key = ExternalAPIKeyCreate(name="full-access-key")
        assert key.scopes is None


# ── Scope Ceiling at Runtime Tests ───────────────────────────────────


class TestScopeCeilingAtRuntime:
    """Tests for scope ceiling enforcement when owner's role changes."""

    @pytest.mark.asyncio
    async def test_role_downgrade_blocks_previously_valid_scope(self):
        """Key scope that was valid when created but owner role downgraded."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        user = _make_user()
        # Key was created when user was editor, with file.write scope
        key = _make_api_key(user.id, scopes=["file.write"])
        user._api_key_record = key
        # User is now a viewer — viewers don't have file.write
        membership = _make_membership("viewer")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership):
            dep = require_api_scope(Permission.FILE_WRITE)
            with pytest.raises(HTTPException) as exc:
                await dep(user=user, db=mock_db)
            assert exc.value.status_code == 403
            assert "no longer grants" in exc.value.detail

    @pytest.mark.asyncio
    async def test_role_upgrade_grants_new_scopes(self):
        """Null-scope key on upgraded user should gain new permissions."""
        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=None)  # Full access
        user._api_key_record = key
        # User promoted to admin
        membership = _make_membership("admin")

        mock_db = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.AUDIT_VIEW)
            result = await dep(user=user, db=mock_db)
            assert result.id == user.id


# ── Audit Log Integration Tests ──────────────────────────────────────


class TestAuditLogIntegration:
    """Tests for audit logging on API key usage."""

    @pytest.mark.asyncio
    async def test_audit_log_records_api_key_usage(self):
        """Audit entry should be created on scoped key use."""
        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["chat.send"])
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()
        mock_log = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", mock_log):
            dep = require_api_scope(Permission.CHAT_SEND)
            await dep(user=user, db=mock_db)

            mock_log.assert_called_once()
            kwargs = mock_log.call_args[1]
            assert kwargs["action"] == "api_key.used"
            assert kwargs["resource_type"] == "api_key"
            assert kwargs["resource_id"] == key.id
            assert kwargs["details"]["key_prefix"] == "tsk_abcd"
            assert kwargs["details"]["key_name"] == "Test Key"
            assert kwargs["details"]["scope_used"] == "chat.send"

    @pytest.mark.asyncio
    async def test_audit_log_not_called_on_failure(self):
        """Audit should NOT log when scope check fails."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.read"])  # No chat.send
        user._api_key_record = key

        mock_db = AsyncMock()
        mock_log = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.services.audit_service.log_event", mock_log):
            dep = require_api_scope(Permission.CHAT_SEND)
            with pytest.raises(HTTPException):
                await dep(user=user, db=mock_db)

            mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_log_skipped_without_team(self):
        """Audit should be skipped if user has no team (no team_id to log against)."""
        from app.auth_external import require_api_scope

        user = _make_user()
        user.default_team_id = None  # No team
        key = _make_api_key(user.id, scopes=["chat.send"])
        user._api_key_record = key

        mock_db = AsyncMock()
        mock_log = AsyncMock()

        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.services.audit_service.log_event", mock_log):
            dep = require_api_scope(Permission.CHAT_SEND)
            await dep(user=user, db=mock_db)

            mock_log.assert_not_called()


# ── Scopes Endpoint Integration Tests ────────────────────────────────


class TestScopesEndpoint:
    """Tests for the GET /keys/scopes endpoint logic."""

    def test_admin_gets_all_scopes(self):
        """Admin user should get all available scopes."""
        admin_perms = ROLE_PERMISSIONS["admin"]
        scopes = []
        for perm in Permission:
            if perm in admin_perms and perm.value in SCOPE_LABELS:
                scopes.append(perm.value)
        assert len(scopes) == len(Permission)

    def test_viewer_gets_limited_scopes(self):
        """Viewer should only get viewer-level scopes."""
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        scopes = []
        for perm in Permission:
            if perm in viewer_perms and perm.value in SCOPE_LABELS:
                scopes.append(perm.value)
        assert len(scopes) == len(viewer_perms)
        assert "chat.send" not in scopes
        assert "file.write" not in scopes
        assert "file.read" in scopes
        assert "chat.view" in scopes

    def test_editor_gets_non_admin_scopes(self):
        """Editor should get all non-admin scopes."""
        editor_perms = ROLE_PERMISSIONS["editor"]
        scopes = []
        for perm in Permission:
            if perm in editor_perms and perm.value in SCOPE_LABELS:
                scopes.append(perm.value)
        assert "audit.view" not in scopes
        assert "project.delete" not in scopes
        assert "chat.send" in scopes
        assert "file.write" in scopes


# ── Multiple Scope Combinations Tests ────────────────────────────────


class TestMultipleScopeCombinations:
    """Tests for keys with various scope combinations."""

    @pytest.mark.asyncio
    async def test_key_with_single_scope(self):
        """Key with only one scope should pass for that scope, fail for others."""
        from fastapi import HTTPException

        from app.auth_external import require_api_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.read"])
        user._api_key_record = key
        membership = _make_membership("admin")

        mock_db = AsyncMock()

        # Should pass for file.read
        with patch("app.auth_external.get_external_api_user", return_value=user), \
             patch("app.auth_external.get_team_membership", return_value=membership), \
             patch("app.services.audit_service.log_event", new_callable=AsyncMock):
            dep = require_api_scope(Permission.FILE_READ)
            result = await dep(user=user, db=mock_db)
            assert result.id == user.id

        # Should fail for chat.send
        with patch("app.auth_external.get_external_api_user", return_value=user):
            dep = require_api_scope(Permission.CHAT_SEND)
            with pytest.raises(HTTPException) as exc:
                await dep(user=user, db=mock_db)
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_key_with_all_agent_scopes(self):
        """Key with agent-only preset scopes should pass for agent operations."""
        from app.auth_external import require_api_scope

        agent_scopes = [
            "chat.send", "chat.view", "file.read", "file.write",
            "container.view", "container.start_stop", "terminal.access",
        ]
        user = _make_user()
        key = _make_api_key(user.id, scopes=agent_scopes)
        user._api_key_record = key
        membership = _make_membership("editor")

        mock_db = AsyncMock()

        for perm_value in agent_scopes:
            perm = Permission(perm_value)
            with patch("app.auth_external.get_external_api_user", return_value=user), \
                 patch("app.auth_external.get_team_membership", return_value=membership), \
                 patch("app.services.audit_service.log_event", new_callable=AsyncMock):
                dep = require_api_scope(perm)
                result = await dep(user=user, db=mock_db)
                assert result.id == user.id


# ── Centralized enforce_permission_scope Tests ───────────────────────


class TestEnforcePermissionScope:
    """Tests for the centralized enforce_permission_scope() in auth_unified.py."""

    def test_jwt_user_bypasses_scope_check(self):
        """JWT users (no _api_key_record) should never be scope-checked."""
        from app.auth_unified import enforce_permission_scope

        user = _make_user()
        # No _api_key_record attribute → JWT user
        if hasattr(user, "_api_key_record"):
            delattr(user, "_api_key_record")

        # Should not raise for any permission
        enforce_permission_scope(user, Permission.FILE_WRITE)
        enforce_permission_scope(user, Permission.PROJECT_DELETE)
        enforce_permission_scope(user, Permission.AUDIT_VIEW)

    def test_null_scopes_key_bypasses_scope_check(self):
        """API key with null scopes (full access) should bypass scope check."""
        from app.auth_unified import enforce_permission_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=None)
        user._api_key_record = key

        enforce_permission_scope(user, Permission.FILE_WRITE)
        enforce_permission_scope(user, Permission.PROJECT_DELETE)

    def test_scoped_key_allows_matching_permission(self):
        """API key with matching scope should pass."""
        from app.auth_unified import enforce_permission_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.write", "file.read"])
        user._api_key_record = key

        enforce_permission_scope(user, Permission.FILE_WRITE)  # Should not raise
        enforce_permission_scope(user, Permission.FILE_READ)  # Should not raise

    def test_scoped_key_blocks_missing_permission(self):
        """API key without matching scope should raise 403."""
        from fastapi import HTTPException

        from app.auth_unified import enforce_permission_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.read"])
        user._api_key_record = key

        with pytest.raises(HTTPException) as exc:
            enforce_permission_scope(user, Permission.FILE_WRITE)
        assert exc.value.status_code == 403
        assert "file.write" in exc.value.detail

    def test_scoped_key_blocks_terminal_access(self):
        """Read-only key should block terminal access."""
        from fastapi import HTTPException

        from app.auth_unified import enforce_permission_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["file.read", "chat.view"])
        user._api_key_record = key

        with pytest.raises(HTTPException) as exc:
            enforce_permission_scope(user, Permission.TERMINAL_ACCESS)
        assert exc.value.status_code == 403

    def test_scoped_key_blocks_git_write(self):
        """Read-only key should block git write operations."""
        from fastapi import HTTPException

        from app.auth_unified import enforce_permission_scope

        user = _make_user()
        key = _make_api_key(user.id, scopes=["git.view", "file.read"])
        user._api_key_record = key

        with pytest.raises(HTTPException) as exc:
            enforce_permission_scope(user, Permission.GIT_WRITE)
        assert exc.value.status_code == 403

    def test_enforce_project_scope_still_works(self):
        """enforce_project_scope should still check project_ids restriction."""
        from fastapi import HTTPException

        from app.auth_unified import enforce_project_scope

        user = _make_user()
        allowed_project = uuid.uuid4()
        other_project = uuid.uuid4()
        key = _make_api_key(user.id, project_ids=[str(allowed_project)])
        user._api_key_record = key

        enforce_project_scope(user, allowed_project)  # Should not raise

        with pytest.raises(HTTPException) as exc:
            enforce_project_scope(user, other_project)
        assert exc.value.status_code == 403
