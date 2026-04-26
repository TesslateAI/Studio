"""Tests for the Phase 3 Connector Proxy.

Covered:
  * Happy path: valid header + grant + allowlisted endpoint → upstream is
    called with the bearer injected, response forwarded, audit row written.
  * exposure='env' grant is rejected with 403 (proxy only handles
    exposure='proxy').
  * No grant for the connector → 403.
  * Endpoint not in the adapter's allowlist → 403, no upstream call.
  * Unknown connector_id → 404.
  * Missing/invalid X-OpenSail-AppInstance → 401.
  * Authorization smuggled by the app pod is stripped before forwarding.
  * Authorization echoed by the upstream is stripped before returning.
  * 401 from upstream → adapter refresh hook fires, request retried once
    with the fresh token.
  * 401 second time → propagates to the caller.
  * Audit row written on every call (success and failure).
  * Audit ``error`` body has Bearer tokens scrubbed.
  * Allowlist parameter-segment matching: ``users/{userId}`` accepts
    ``users/me`` but rejects ``users/me/extra`` and ``users/..``.

Strategy
--------
We build a minimal FastAPI app that mounts only the connector_proxy
router, override ``app.database.get_db`` to point at an in-memory SQLite
session, and use ``respx`` to intercept the outbound httpx calls. This
keeps the test hermetic — no Postgres, no real Slack, no orchestrator
boot.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base, get_db
from app.models import McpOAuthConnection, User, UserMcpConfig
from app.models_automations import (
    AppConnectorGrant,
    AppConnectorRequirement,
    AppInstance,
    ConnectorProxyCall,
)
from app.services.apps.connector_proxy import router as connector_proxy_router
from app.services.apps.connector_proxy.audit import scrub_error_body
from app.services.apps.connector_proxy.provider_adapters import (
    ADAPTER_REGISTRY,
)
from app.services.apps.connector_proxy.provider_adapters.base import (
    AllowedEndpoint,
)
from app.services.channels.registry import encrypt_credentials


# ---------------------------------------------------------------------------
# Schema/seed helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    """Per-test in-memory SQLite engine with the full app schema.

    Uses ``StaticPool`` so all sessions opened against the engine share a
    single underlying connection — required for ``:memory:`` databases
    because each fresh connection otherwise opens a new empty DB.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    """FastAPI test client with get_db overridden to use the in-memory engine."""
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_test_db():
        async with maker() as session:
            try:
                yield session
            finally:
                await session.close()

    fastapi_app = FastAPI()
    fastapi_app.include_router(connector_proxy_router)
    fastapi_app.dependency_overrides[get_db] = _get_test_db

    with TestClient(fastapi_app) as tc:
        yield tc


async def _seed_oauth_install(
    db: AsyncSession,
    *,
    connector_id: str = "slack",
    exposure_at_grant: str = "proxy",
    access_token: str = "xoxb-fake-test-token-1234567890ab",
    create_grant: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed enough rows so a proxy call resolves end-to-end.

    Returns ``(app_instance_id, oauth_connection_id)``.
    """
    uid = uuid.uuid4()
    user = User(
        id=uid,
        email=f"u-{uid}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=False,
        name="Test User",
        username=f"user-{uid.hex[:10]}",
        slug=f"user-{uid.hex[:10]}",
    )
    db.add(user)

    # AppInstance needs app_id + app_version_id FKs; create the minimal
    # marketplace_apps + app_versions rows.
    from app.models import AppVersion, MarketplaceApp

    mkt = MarketplaceApp(
        id=uuid.uuid4(),
        slug=f"app-{uuid.uuid4().hex[:8]}",
        name="Test App",
        creator_user_id=user.id,
    )
    db.add(mkt)
    av = AppVersion(
        id=uuid.uuid4(),
        app_id=mkt.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={},
        manifest_hash="hash-" + uuid.uuid4().hex[:16],
        feature_set_hash="fs-" + uuid.uuid4().hex[:16],
    )
    db.add(av)
    await db.flush()

    instance = AppInstance(
        id=uuid.uuid4(),
        app_id=mkt.id,
        app_version_id=av.id,
        installer_user_id=user.id,
        state="installed",
    )
    db.add(instance)

    requirement = AppConnectorRequirement(
        id=uuid.uuid4(),
        app_version_id=av.id,
        connector_id=connector_id,
        kind="oauth",
        scopes=[],
        exposure="proxy",
    )
    db.add(requirement)

    # Encrypt the OAuth tokens shape used in production: a JSON dict with
    # `access_token` (and optionally `refresh_token`, `expires_in`).
    user_mcp = UserMcpConfig(
        id=uuid.uuid4(),
        user_id=user.id,
        scope_level="user",
        is_active=True,
    )
    db.add(user_mcp)
    await db.flush()

    encrypted_tokens = encrypt_credentials(
        {"access_token": access_token, "token_type": "Bearer"}
    )
    encrypted_client_info = encrypt_credentials({"client_id": "test-client"})
    oauth = McpOAuthConnection(
        id=uuid.uuid4(),
        user_mcp_config_id=user_mcp.id,
        server_url="https://example.test",
        tokens_encrypted=encrypted_tokens,
        client_info_encrypted=encrypted_client_info,
        registration_method="dcr",
    )
    db.add(oauth)
    await db.flush()

    if create_grant:
        grant = AppConnectorGrant(
            id=uuid.uuid4(),
            app_instance_id=instance.id,
            requirement_id=requirement.id,
            resolved_ref={"kind": "oauth_connection", "id": str(oauth.id)},
            exposure_at_grant=exposure_at_grant,
            granted_by_user_id=user.id,
        )
        db.add(grant)

    await db.commit()
    return instance.id, oauth.id


# ---------------------------------------------------------------------------
# Adapter unit tests (no DB / no HTTP).
# ---------------------------------------------------------------------------


def test_registry_has_four_adapters() -> None:
    keys = set(ADAPTER_REGISTRY.keys())
    assert keys == {"slack", "github", "linear", "gmail"}


def test_slack_endpoint_allowlist_includes_chat_post_message() -> None:
    slack = ADAPTER_REGISTRY.get("slack")
    assert slack is not None
    assert slack.is_allowed("POST", "chat.postMessage") is True
    assert slack.is_allowed("POST", "/chat.postMessage") is True  # leading /
    assert slack.is_allowed("DELETE", "chat.postMessage") is False
    assert slack.is_allowed("POST", "chat.totallyMadeUp") is False


def test_github_parameterized_endpoint_matches_segments() -> None:
    gh = ADAPTER_REGISTRY.get("github")
    assert gh is not None
    assert gh.is_allowed("GET", "repos/octocat/hello-world") is True
    assert gh.is_allowed("GET", "repos/octocat/hello-world/issues") is True
    # Wrong arity must NOT match.
    assert gh.is_allowed("GET", "repos/octocat") is False
    assert gh.is_allowed("GET", "repos/octocat/hello-world/extra/garbage") is False
    # Path traversal in the placeholder slot is rejected.
    assert gh.is_allowed("GET", "repos/../../escape/blah") is False


def test_endpoint_match_rejects_double_dot_in_placeholder() -> None:
    ep = AllowedEndpoint(method="GET", path="users/{id}")
    assert ep.matches("GET", "users/abc") is True
    assert ep.matches("GET", "users/..") is False


def test_scrub_error_body_strips_bearer_tokens() -> None:
    body = (
        'oh no the upstream said {"error":"Authorization: Bearer xoxb-secretsecret"} '
        "and also Bearer abcdefghijklmnop1234"
    )
    scrubbed = scrub_error_body(body)
    assert scrubbed is not None
    assert "xoxb-secretsecret" not in scrubbed
    assert "abcdefghijklmnop1234" not in scrubbed
    assert "REDACTED" in scrubbed.upper() or "[redacted]" in scrubbed.lower()


# ---------------------------------------------------------------------------
# Auth / grant / allowlist gate tests.
# ---------------------------------------------------------------------------


def test_missing_app_instance_header_returns_401(client: TestClient) -> None:
    resp = client.post("/api/v1/connector-proxy/connectors/slack/chat.postMessage")
    assert resp.status_code == 401
    assert "X-OpenSail-AppInstance" in resp.json()["detail"]


def test_invalid_app_instance_header_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
        headers={"X-OpenSail-AppInstance": "not-a-uuid"},
    )
    assert resp.status_code == 401


def test_unknown_app_instance_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
        headers={"X-OpenSail-AppInstance": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_no_grant_returns_403(client: TestClient, db_session: AsyncSession) -> None:
    instance_id, _ = await _seed_oauth_install(
        db_session, create_grant=False
    )
    resp = client.post(
        "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
        headers={"X-OpenSail-AppInstance": str(instance_id)},
    )
    assert resp.status_code == 403
    assert "no active grant" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_env_exposure_grant_returns_403(
    client: TestClient, db_session: AsyncSession
) -> None:
    instance_id, _ = await _seed_oauth_install(
        db_session, exposure_at_grant="env"
    )
    resp = client.post(
        "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
        headers={"X-OpenSail-AppInstance": str(instance_id)},
    )
    assert resp.status_code == 403
    assert "exposure='env'" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_connector_returns_404(
    client: TestClient, db_session: AsyncSession
) -> None:
    instance_id, _ = await _seed_oauth_install(
        db_session, connector_id="not-a-real-connector"
    )
    resp = client.post(
        "/api/v1/connector-proxy/connectors/not-a-real-connector/anything",
        headers={"X-OpenSail-AppInstance": str(instance_id)},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_not_in_allowlist_returns_403(
    client: TestClient, db_session: AsyncSession
) -> None:
    instance_id, _ = await _seed_oauth_install(db_session)
    with respx.mock(assert_all_called=False) as router:
        # If the proxy were buggy and forwarded anyway, the request would
        # fail because we registered no upstream mock.
        upstream = router.post("https://slack.com/api/totally.fake").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/totally.fake",
            headers={"X-OpenSail-AppInstance": str(instance_id)},
        )
    assert resp.status_code == 403
    assert "allowlist" in resp.json()["detail"]
    assert upstream.called is False


# ---------------------------------------------------------------------------
# Happy path + token-isolation tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_injects_bearer_and_records_audit(
    client: TestClient, db_session: AsyncSession
) -> None:
    token = "xoxb-fake-test-token-happy-path"
    instance_id, _ = await _seed_oauth_install(db_session, access_token=token)

    captured = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "ts": "1234.5"})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://slack.com/api/chat.postMessage").mock(
            side_effect=_record
        )
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            headers={
                "X-OpenSail-AppInstance": str(instance_id),
                "Content-Type": "application/json",
                # The app pod tries to smuggle its own Authorization — must be stripped.
                "Authorization": "Bearer pretend-rogue-app-token",
            },
            json={"channel": "C123", "text": "hi"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "ts": "1234.5"}

    # Bearer was injected by the proxy.
    assert captured["headers"].get("authorization") == f"Bearer {token}"
    # Smuggled Authorization was stripped.
    assert "pretend-rogue-app-token" not in captured["headers"].get(
        "authorization", ""
    )
    # OpenSail header was stripped from upstream.
    assert "x-opensail-appinstance" not in {
        k.lower() for k in captured["headers"]
    }
    # Body forwarded intact.
    assert json.loads(captured["body"]) == {"channel": "C123", "text": "hi"}

    # Audit row written.
    rows = (
        await db_session.execute(
            select(ConnectorProxyCall).where(
                ConnectorProxyCall.app_instance_id == instance_id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    audit_row = rows[0]
    assert audit_row.connector_id == "slack"
    assert audit_row.endpoint == "chat.postMessage"
    assert audit_row.status_code == 200
    assert audit_row.error is None
    assert audit_row.bytes_in > 0
    assert audit_row.bytes_out > 0


@pytest.mark.asyncio
async def test_response_strips_authorization_echo(
    client: TestClient, db_session: AsyncSession
) -> None:
    """If upstream echoes Authorization, the proxy strips it before returning."""
    instance_id, _ = await _seed_oauth_install(db_session)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://slack.com/api/auth.test").mock(
            return_value=httpx.Response(
                200,
                json={"ok": True},
                headers={
                    "Authorization": "Bearer leaked-via-echo",
                    "X-Custom-Echo": "fine",
                },
            )
        )
        resp = client.get(
            "/api/v1/connector-proxy/connectors/slack/auth.test",
            headers={"X-OpenSail-AppInstance": str(instance_id)},
        )

    assert resp.status_code == 200
    # Authorization is NOT in response headers — proxy strips it.
    assert "authorization" not in {k.lower() for k in resp.headers}
    # Other custom headers pass through.
    assert resp.headers.get("X-Custom-Echo") == "fine"


@pytest.mark.asyncio
async def test_audit_records_error_body_for_4xx(
    client: TestClient, db_session: AsyncSession
) -> None:
    instance_id, _ = await _seed_oauth_install(db_session)

    with respx.mock(assert_all_called=True) as router:
        router.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(
                400,
                json={"ok": False, "error": "channel_not_found"},
            )
        )
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            headers={"X-OpenSail-AppInstance": str(instance_id)},
            json={"channel": "C-NOPE", "text": "hi"},
        )

    assert resp.status_code == 400
    rows = (
        await db_session.execute(select(ConnectorProxyCall))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status_code == 400
    assert rows[0].error is not None
    assert "channel_not_found" in rows[0].error


# ---------------------------------------------------------------------------
# 401 → refresh-once retry path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_with_refresh_hook_retries_once(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter exposes a refresh hook → 401 triggers refresh + one retry."""
    token_old = "xoxb-old-token-aaaaaaaaaaaaaaaa"
    token_new = "xoxb-new-token-bbbbbbbbbbbbbbbb"
    instance_id, oauth_id = await _seed_oauth_install(
        db_session, access_token=token_old
    )

    refresh_calls = []

    async def fake_refresh(db, oauth_connection_id):
        refresh_calls.append(oauth_connection_id)
        return token_new

    slack = ADAPTER_REGISTRY.get("slack")
    assert slack is not None
    monkeypatch.setattr(slack, "refresh_hook", fake_refresh)

    request_count = {"n": 0}

    def _responder(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        seen_token = request.headers.get("authorization", "")
        if request_count["n"] == 1:
            # First call carries the OLD token → 401.
            assert token_old in seen_token
            return httpx.Response(401, json={"ok": False, "error": "invalid_auth"})
        # Second call carries the NEW token → 200.
        assert token_new in seen_token
        return httpx.Response(200, json={"ok": True, "ts": "9.9"})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://slack.com/api/chat.postMessage").mock(
            side_effect=_responder
        )
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            headers={"X-OpenSail-AppInstance": str(instance_id)},
            json={"channel": "C1", "text": "hi"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "ts": "9.9"}
    assert request_count["n"] == 2  # exactly one retry
    assert refresh_calls == [oauth_id]


@pytest.mark.asyncio
async def test_401_second_time_propagates_to_caller(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the upstream still 401s after refresh, propagate the 401."""
    instance_id, _ = await _seed_oauth_install(db_session)

    async def fake_refresh(db, oauth_connection_id):
        return "xoxb-still-bad-zzzzzzzzzzzzzzzzz"

    slack = ADAPTER_REGISTRY.get("slack")
    assert slack is not None
    monkeypatch.setattr(slack, "refresh_hook", fake_refresh)

    request_count = {"n": 0}

    def _always_401(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(401, json={"ok": False, "error": "invalid_auth"})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://slack.com/api/chat.postMessage").mock(
            side_effect=_always_401
        )
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            headers={"X-OpenSail-AppInstance": str(instance_id)},
            json={"channel": "C1", "text": "hi"},
        )

    assert resp.status_code == 401
    # One initial + one retry. We don't try a third time.
    assert request_count["n"] == 2

    # Both attempts produced exactly one audit row (the final outcome).
    rows = (
        await db_session.execute(select(ConnectorProxyCall))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status_code == 401


@pytest.mark.asyncio
async def test_401_without_refresh_hook_propagates(
    client: TestClient, db_session: AsyncSession
) -> None:
    """Slack's default adapter has no refresh_hook — 401 just returns 401."""
    instance_id, _ = await _seed_oauth_install(db_session)
    # Confirm Slack ships with no refresh hook (the default we depend on).
    slack = ADAPTER_REGISTRY.get("slack")
    assert slack is not None and slack.refresh_hook is None

    request_count = {"n": 0}

    def _once_401(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(401, json={"ok": False, "error": "invalid_auth"})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://slack.com/api/chat.postMessage").mock(
            side_effect=_once_401
        )
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            headers={"X-OpenSail-AppInstance": str(instance_id)},
            json={"channel": "C1"},
        )

    assert resp.status_code == 401
    assert request_count["n"] == 1  # NO retry without a refresh hook
