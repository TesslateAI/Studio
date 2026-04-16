"""
Regression tests for the chat WebSocket project-access authorization
(security issue #343).

**Pre-fix behavior (exploit)**: `/api/chat/ws/{token}` accepts any `project_id`
from the first WS message and proceeds to query `project_files` / `chats`
without verifying the caller has access to that project. A free-tier user can
read any project's file contents + chat history by supplying a victim UUID.

**Post-fix behavior**: the handler must call `_authorize_ws_project_access()`
before registering the connection or invoking `handle_chat_message`. When the
helper denies access, the WebSocket must be closed with code 1008 and
`handle_chat_message` must NOT be invoked.

These tests MUST fail against the pre-fix code (no helper exists, no check is
wired into the endpoint) and pass after the fix lands.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

import app.models  # noqa: F401 — register ORM models

# ── Mock-DB helpers (mirroring tests/rbac/test_permissions.py) ──────────


def _make_user(is_superuser=False, user_id=None):
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.username = "testuser"
    u.is_superuser = is_superuser
    u.is_active = True
    return u


def _make_project(project_id=None, owner_id=None, team_id=None, visibility="private"):
    p = MagicMock()
    p.id = project_id or uuid.uuid4()
    p.slug = "victim-project"
    p.owner_id = owner_id or uuid.uuid4()
    p.team_id = team_id
    p.visibility = visibility
    return p


def _make_team_membership(role, is_active=True):
    m = MagicMock()
    m.role = role
    m.is_active = is_active
    return m


def _db_returning(*scalars):
    """Mock DB whose `.execute().scalar_one_or_none()` returns the given values in order."""
    db = AsyncMock()
    results = []
    for s in scalars:
        r = MagicMock()
        r.scalar_one_or_none.return_value = s
        results.append(r)
    db.execute.side_effect = results
    return db


# ── Helper unit tests ──────────────────────────────────────────────────
#
# These tests require the new helper to exist. Before the fix lands, the
# import alone fails → every test in this class errors out, proving the
# fix is missing.


class TestAuthorizeWsProjectAccess:
    """Unit tests for the new _authorize_ws_project_access helper."""

    @pytest.mark.asyncio
    async def test_missing_project_id_denied(self):
        from app.routers.chat import _authorize_ws_project_access

        user = _make_user()
        db = AsyncMock()
        project, reason = await _authorize_ws_project_access(db, user, None)
        assert project is None
        assert reason  # non-empty denial reason
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_project_id_denied(self):
        from app.routers.chat import _authorize_ws_project_access

        user = _make_user()
        db = AsyncMock()
        project, reason = await _authorize_ws_project_access(db, user, "")
        assert project is None
        assert reason

    @pytest.mark.asyncio
    async def test_invalid_uuid_denied(self):
        from app.routers.chat import _authorize_ws_project_access

        user = _make_user()
        db = AsyncMock()
        project, reason = await _authorize_ws_project_access(db, user, "not-a-uuid")
        assert project is None
        assert reason
        # No DB lookup should happen for malformed UUIDs
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_nonexistent_project_denied(self):
        from app.routers.chat import _authorize_ws_project_access

        user = _make_user()
        # First query (Project lookup) returns None
        db = _db_returning(None)
        project, reason = await _authorize_ws_project_access(db, user, str(uuid.uuid4()))
        assert project is None
        assert reason

    @pytest.mark.asyncio
    async def test_non_member_denied(self):
        """Core exploit-blocking case: user has no membership on target project."""
        from app.routers.chat import _authorize_ws_project_access

        attacker = _make_user()
        victim_project = _make_project(owner_id=uuid.uuid4(), team_id=None, visibility="private")

        # Queries in order:
        #   1. Project lookup (returns the victim project)
        #   2. User lookup inside get_effective_project_role (is_superuser check)
        #   3. ProjectMembership lookup (None — attacker has no override)
        db = _db_returning(
            victim_project,
            _make_user(is_superuser=False),
            None,
        )

        project, reason = await _authorize_ws_project_access(db, attacker, str(victim_project.id))
        assert project is None, "attacker must not receive the project row"
        assert reason

    @pytest.mark.asyncio
    async def test_owner_allowed(self):
        from app.routers.chat import _authorize_ws_project_access

        owner = _make_user()
        proj = _make_project(owner_id=owner.id, team_id=None, visibility="private")

        db = _db_returning(
            proj,  # Project lookup
            _make_user(is_superuser=False),  # User lookup in get_effective_project_role
            None,  # No project membership row — falls through to owner_id legacy compat
        )

        project, reason = await _authorize_ws_project_access(db, owner, str(proj.id))
        assert project is proj
        assert reason is None

    @pytest.mark.asyncio
    async def test_team_editor_allowed(self):
        from app.routers.chat import _authorize_ws_project_access

        editor = _make_user()
        team_id = uuid.uuid4()
        proj = _make_project(owner_id=uuid.uuid4(), team_id=team_id, visibility="team")

        # Project lookup → user lookup (superuser check) → team membership → project membership
        db = _db_returning(
            proj,
            _make_user(is_superuser=False),
            _make_team_membership("editor"),
            None,
        )

        project, reason = await _authorize_ws_project_access(db, editor, str(proj.id))
        assert project is proj
        assert reason is None

    @pytest.mark.asyncio
    async def test_superuser_allowed(self):
        from app.routers.chat import _authorize_ws_project_access

        admin = _make_user(is_superuser=True)
        proj = _make_project(owner_id=uuid.uuid4())

        # Project lookup → user lookup (returns superuser) — shortcut
        db = _db_returning(
            proj,
            _make_user(is_superuser=True),
        )

        project, reason = await _authorize_ws_project_access(db, admin, str(proj.id))
        assert project is proj
        assert reason is None


# ── End-to-end WS endpoint regression test ─────────────────────────────
#
# This is the canonical exploit reproduction: build a JWT for a freshly
# registered user, simulate the WS connecting and supplying a victim
# project_id, and assert the endpoint closes with 1008 BEFORE
# handle_chat_message runs.


@pytest.mark.asyncio
async def test_ws_endpoint_rejects_unauthorized_project_id():
    """
    Pre-fix: endpoint happily registers the connection and calls
    handle_chat_message with the victim's project_id → exploit succeeds.
    Post-fix: endpoint closes WS with code 1008 and never invokes
    handle_chat_message.
    """
    from app.config import get_settings
    from app.routers import chat as chat_router

    settings = get_settings()

    attacker_id = uuid.uuid4()
    attacker = _make_user(user_id=attacker_id)
    attacker.id = attacker_id  # Ensure UUID type

    victim_project = _make_project(owner_id=uuid.uuid4(), team_id=None, visibility="private")

    # Mocked WebSocket — records close() calls, feeds a single exploit message.
    ws = AsyncMock()
    exploit_message = {
        "project_id": str(victim_project.id),
        "message": "read every file in this project",
    }
    ws.receive_json = AsyncMock(side_effect=[exploit_message])

    # Mocked DB: User lookup (attacker), Project lookup (victim project),
    # User lookup inside get_effective_project_role, ProjectMembership None.
    db = _db_returning(
        attacker,  # 1. JWT sub → User lookup in websocket_endpoint
        victim_project,  # 2. Project lookup in helper
        _make_user(is_superuser=False),  # 3. User lookup in get_effective_project_role
        None,  # 4. ProjectMembership lookup (none — attacker is a stranger)
    )

    # Valid JWT signed with the app's secret, sub=attacker_id.
    token = jwt.encode(
        {"sub": str(attacker_id), "aud": "fastapi-users:auth"},
        settings.secret_key,
        algorithm=settings.algorithm,
    )

    # Track whether handle_chat_message is invoked — after the fix, it must NOT be.
    called_with: list = []

    async def spy_handle_chat_message(*args, **kwargs):
        called_with.append((args, kwargs))

    with patch.object(chat_router, "handle_chat_message", spy_handle_chat_message):
        await chat_router.websocket_endpoint(ws, token, db)

    # The endpoint must close the WS (close call must have happened)
    assert ws.close.called, "WebSocket must be closed when project access is denied"

    # And specifically with 1008 (policy violation)
    close_codes = [
        (c.kwargs.get("code") if c.kwargs else None) or (c.args[0] if c.args else None)
        for c in ws.close.call_args_list
    ]
    assert 1008 in close_codes, (
        f"Expected close code 1008 for unauthorized project access, got {close_codes}"
    )

    # Critical: handle_chat_message must NOT have been reached.
    assert called_with == [], (
        "handle_chat_message must NOT be invoked when project access is denied — "
        "this is the exploit surface"
    )


@pytest.mark.asyncio
async def test_ws_endpoint_allows_owner():
    """
    Positive case: the owner of a project connects and supplies their own
    project_id. handle_chat_message must be invoked.
    """
    from app.config import get_settings
    from app.routers import chat as chat_router

    settings = get_settings()

    owner_id = uuid.uuid4()
    owner = _make_user(user_id=owner_id)
    owner.id = owner_id
    proj = _make_project(owner_id=owner_id, team_id=None, visibility="private")

    ws = AsyncMock()
    ws.receive_json = AsyncMock(
        side_effect=[
            {"project_id": str(proj.id), "message": "hello"},
            WebSocketDisconnect(),  # Exit the outer while True via break
        ]
    )

    db = _db_returning(
        owner,
        proj,
        _make_user(is_superuser=False),
        None,  # No project membership; owner_id legacy path grants admin
    )

    token = jwt.encode(
        {"sub": str(owner_id), "aud": "fastapi-users:auth"},
        settings.secret_key,
        algorithm=settings.algorithm,
    )

    handle_called = []

    async def spy(*args, **kwargs):
        handle_called.append(True)

    with patch.object(chat_router, "handle_chat_message", spy):
        await chat_router.websocket_endpoint(ws, token, db)

    assert handle_called, "handle_chat_message should be called for the legitimate owner"
