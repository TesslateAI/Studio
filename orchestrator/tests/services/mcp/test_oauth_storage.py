"""Unit tests for :mod:`app.services.mcp.oauth_storage`.

Uses an in-memory stub ``AsyncSession`` — full DB is exercised in the
integration tests. These tests focus on:

- Tokens and client_info round-trip through Fernet encryption.
- ``set_tokens`` without a pre-existing row raises a clear RuntimeError.
- Decrypt failure returns ``None`` (defensive).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.models import McpOAuthConnection
from app.services.mcp.oauth_storage import PostgresTokenStorage

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(row: McpOAuthConnection | None):
    """Return a MagicMock AsyncSession whose ``execute`` yields ``row``."""
    db = MagicMock()
    scalar_one_or_none = MagicMock(return_value=row)
    result_obj = MagicMock()
    result_obj.scalar_one_or_none = scalar_one_or_none
    db.execute = AsyncMock(return_value=result_obj)
    db.flush = AsyncMock()
    return db


def _make_row() -> McpOAuthConnection:
    row = McpOAuthConnection()
    row.id = uuid4()
    row.user_mcp_config_id = uuid4()
    row.server_url = "https://mcp.example.com/mcp"
    row.tokens_encrypted = ""
    row.client_info_encrypted = ""
    row.registration_method = "dcr"
    return row


def _client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        redirect_uris=["https://app.tesslate.com/api/mcp/oauth/callback"],
        token_endpoint_auth_method="client_secret_basic",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="OpenSail",
        client_id="cid-abc",
        client_secret="s3cret",
    )


def _token() -> OAuthToken:
    return OAuthToken(
        access_token="access-xyz",
        token_type="Bearer",
        expires_in=3600,
        refresh_token="refresh-xyz",
        scope="read write",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_client_info_then_set_and_get_tokens_roundtrip(monkeypatch):
    """set_client_info upserts, then set_tokens persists + get_tokens decrypts."""
    row = _make_row()
    db = _make_db(row)
    storage = PostgresTokenStorage(db, row.user_mcp_config_id)

    info = _client_info()
    await storage.set_client_info(info)
    assert row.client_info_encrypted, "client_info should be encrypted and persisted"

    got_info = await storage.get_client_info()
    assert got_info is not None
    assert got_info.client_id == "cid-abc"
    assert got_info.client_secret == "s3cret"

    tok = _token()
    await storage.set_tokens(tok)
    assert row.tokens_encrypted, "tokens should be encrypted and persisted"
    assert row.token_expires_at is not None, "expires_at must be set"
    assert row.last_refresh_at is not None, "last_refresh_at must be set"

    got_tok = await storage.get_tokens()
    assert got_tok is not None
    assert got_tok.access_token == "access-xyz"
    assert got_tok.refresh_token == "refresh-xyz"


@pytest.mark.asyncio
async def test_set_tokens_without_existing_row_raises():
    db = _make_db(None)
    storage = PostgresTokenStorage(db, uuid4())
    with pytest.raises(RuntimeError):
        await storage.set_tokens(_token())


@pytest.mark.asyncio
async def test_set_client_info_without_existing_row_raises():
    db = _make_db(None)
    storage = PostgresTokenStorage(db, uuid4())
    with pytest.raises(RuntimeError):
        await storage.set_client_info(_client_info())


@pytest.mark.asyncio
async def test_get_tokens_returns_none_on_decrypt_failure():
    row = _make_row()
    row.tokens_encrypted = "not-a-valid-fernet-blob"
    db = _make_db(row)
    storage = PostgresTokenStorage(db, row.user_mcp_config_id)
    assert await storage.get_tokens() is None


@pytest.mark.asyncio
async def test_get_tokens_returns_none_when_row_missing():
    db = _make_db(None)
    storage = PostgresTokenStorage(db, uuid4())
    assert await storage.get_tokens() is None
    assert await storage.get_client_info() is None
