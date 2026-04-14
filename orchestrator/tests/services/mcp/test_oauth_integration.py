"""Integration test for the MCP OAuth start → callback flow.

Stubs out:
- ``httpx.AsyncClient`` GET/POST responses for PRM, AS metadata, DCR, and
  token exchange.
- ``cache_service.get_redis_client`` with an in-memory dict-backed double so
  flow state can round-trip through Redis without a real server.
- ``encrypt_credentials``/``decrypt_credentials`` via the real Fernet since
  the env-set ``SECRET_KEY`` in conftest is sufficient.

The test exercises the public API (``start_oauth_flow`` +
``complete_oauth_flow``) and verifies both the DB row for
``UserMcpConfig`` and the paired ``McpOAuthConnection`` are created
correctly.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# In-memory Redis double
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal async Redis surface used by oauth_flow.py."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float]] = {}

    async def setex(self, key: str, ttl: int, value: Any) -> None:
        self.store[key] = (value if isinstance(value, str) else value.decode(), time.time() + ttl)

    async def get(self, key: str) -> str | None:
        entry = self.store.get(key)
        if not entry:
            return None
        value, expires = entry
        if expires < time.time():
            self.store.pop(key, None)
            return None
        return value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


# ---------------------------------------------------------------------------
# httpx.AsyncClient double
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or json.dumps(self._json)

    def json(self) -> dict:
        return self._json


class _RouterClient:
    """Async context-manager httpx client that answers from a static routing
    table keyed on ``(method, url)``."""

    def __init__(self, routes: dict[tuple[str, str], _FakeResponse]):
        self._routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, **_: Any) -> _FakeResponse:
        r = self._routes.get(("GET", url))
        if not r:
            return _FakeResponse(404)
        return r

    async def post(self, url: str, **_: Any) -> _FakeResponse:
        r = self._routes.get(("POST", url))
        if not r:
            return _FakeResponse(400, {"error": "not routed"})
        return r


# ---------------------------------------------------------------------------
# DB double
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    """Captures UserMcpConfig + McpOAuthConnection inserts without hitting PG."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.executed: list[Any] = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        # Return "no existing row" for all lookups.
        return _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)
        from uuid import uuid4 as _u

        if getattr(obj, "id", None) is None:
            obj.id = _u()

    async def flush(self):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SERVER = "https://mcp.example.com/mcp"
AUTH = "https://auth.example.com"
AUTHORIZE = f"{AUTH}/oauth/authorize"
TOKEN = f"{AUTH}/oauth/token"
REGISTRATION = f"{AUTH}/oauth/register"


def _build_routes() -> dict[tuple[str, str], _FakeResponse]:
    prm_urls = [
        f"{SERVER}/.well-known/oauth-protected-resource",
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
        "https://mcp.example.com/.well-known/oauth-protected-resource",
    ]
    as_urls = [
        f"{AUTH}/.well-known/oauth-authorization-server",
        f"{AUTH}/.well-known/openid-configuration",
    ]
    routes: dict[tuple[str, str], _FakeResponse] = {}
    for u in prm_urls:
        routes[("GET", u)] = _FakeResponse(
            200,
            {
                "resource": SERVER,
                "authorization_servers": [AUTH],
            },
        )
    for u in as_urls:
        routes[("GET", u)] = _FakeResponse(
            200,
            {
                "issuer": AUTH,
                "authorization_endpoint": AUTHORIZE,
                "token_endpoint": TOKEN,
                "registration_endpoint": REGISTRATION,
                "code_challenge_methods_supported": ["S256"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "response_types_supported": ["code"],
            },
        )
    routes[("POST", REGISTRATION)] = _FakeResponse(
        201,
        {
            "client_id": "dcr-client-id",
            "client_secret": "dcr-client-secret",
            "client_id_issued_at": int(time.time()),
            "client_secret_expires_at": 0,
            "redirect_uris": ["https://cb.example.com/cb"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )
    routes[("POST", TOKEN)] = _FakeResponse(
        200,
        {
            "access_token": "at-1",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "rt-1",
            "scope": "read write",
        },
    )
    return routes


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dcr_start_and_complete_end_to_end(monkeypatch):
    """DCR happy path: /start discovers, registers, returns authorize URL;
    /complete exchanges the code and persists tokens via Fernet."""

    from app.services.mcp import oauth_flow

    # Redis double
    fake_redis = _FakeRedis()
    monkeypatch.setattr(
        oauth_flow,
        "get_redis_client",
        AsyncMock(return_value=fake_redis),
    )

    # httpx client double
    routes = _build_routes()
    import httpx as _httpx

    def _fake_client(*args, **kwargs):
        return _RouterClient(routes)

    monkeypatch.setattr(_httpx, "AsyncClient", _fake_client)

    db = _FakeDB()
    user_id = uuid4()

    result = await oauth_flow.start_oauth_flow(
        db=db,  # type: ignore[arg-type]
        user_id=user_id,
        server_url=SERVER,
        registration_method="dcr",
        redirect_uri="https://cb.example.com/cb",
    )
    assert result.authorize_url.startswith(AUTHORIZE + "?")
    assert "code_challenge" in result.authorize_url
    assert "code_challenge_method=S256" in result.authorize_url
    assert "resource=" in result.authorize_url

    # Derive state from flow state stored in redis
    keys = [k for k in fake_redis.store if k.startswith("mcp:oauth:flow:") and not k.startswith("mcp:oauth:flow:id:")]
    assert len(keys) == 1, keys
    state = keys[0].rsplit(":", 1)[-1]

    # /callback: run complete_oauth_flow
    config = await oauth_flow.complete_oauth_flow(
        db=db,  # type: ignore[arg-type]
        state=state,
        code="some-code",
    )

    # Row asserts: UserMcpConfig + McpOAuthConnection added, state removed.
    from app.models import McpOAuthConnection, UserMcpConfig

    added_types = {type(obj).__name__ for obj in db.added}
    assert "UserMcpConfig" in added_types
    assert "McpOAuthConnection" in added_types
    assert config is not None
    assert config.scope_level == "user"
    # Flow state key removed after completion.
    assert f"mcp:oauth:flow:{state}" not in fake_redis.store
