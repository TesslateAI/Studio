"""Unit tests for desktop pairing router helpers."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401 — register all ORM models
from app.permissions import Permission
from app.routers.desktop_pair import _resolve_owner_scopes


def _user(default_team_id=None):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.default_team_id = default_team_id
    return u


@pytest.mark.asyncio
async def test_resolve_scopes_defaults_include_desktop_pair():
    db = AsyncMock()
    scopes = await _resolve_owner_scopes(db, _user(), None)
    assert Permission.DESKTOP_PAIR.value in scopes
    assert Permission.MARKETPLACE_READ.value in scopes


@pytest.mark.asyncio
async def test_resolve_scopes_rejects_unknown_scope():
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await _resolve_owner_scopes(db, _user(), ["not.a.real.scope"])
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_scopes_rejects_scope_above_role(monkeypatch):
    team_id = uuid.uuid4()
    user = _user(default_team_id=team_id)

    membership = MagicMock()
    membership.role = "viewer"

    async def _mock_membership(_db, _team_id, _user_id):
        return membership

    monkeypatch.setattr("app.routers.desktop_pair.get_team_membership", _mock_membership)

    db = AsyncMock()
    # viewer does not have project.delete
    with pytest.raises(HTTPException) as exc:
        await _resolve_owner_scopes(db, user, [Permission.PROJECT_DELETE.value])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_resolve_scopes_forces_desktop_pair_when_missing(monkeypatch):
    team_id = uuid.uuid4()
    user = _user(default_team_id=team_id)
    membership = MagicMock()
    membership.role = "admin"

    async def _mock_membership(_db, _team_id, _user_id):
        return membership

    monkeypatch.setattr("app.routers.desktop_pair.get_team_membership", _mock_membership)

    scopes = await _resolve_owner_scopes(
        AsyncMock(), user, [Permission.MODELS_PROXY.value]
    )
    assert Permission.DESKTOP_PAIR.value in scopes
    assert Permission.MODELS_PROXY.value in scopes
