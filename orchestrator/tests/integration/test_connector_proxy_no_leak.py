"""Connector Proxy token-isolation contract (demo flow #18-19).

Two surfaces under test:

1. **Proxy-call path** — an app pod calls
   ``POST /api/v1/connector-proxy/connectors/slack/chat.postMessage``
   with the signed ``X-OpenSail-AppInstance`` header. The proxy:
     * resolves the per-instance grant -> credential row,
     * decrypts the OAuth token server-side,
     * forwards the upstream call with ``Authorization: Bearer <token>``,
     * audits the call in ``connector_proxy_calls``,
     * strips the Authorization header from the response.
   The app pod NEVER sees the token (no Authorization header in the
   forwarded request body, no Authorization header in the proxy's
   response back to the pod).

2. **Manifest-validation path** — the app manifest schema rejects
   ``kind='oauth'`` + ``exposure='env'`` at install time. Handing a
   rotating OAuth token to the app process via env defeats rotation.

Both tests are unit-style — no real K8s, no real Slack. We mock
``httpx.AsyncClient`` so we can introspect the outbound call.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock  # noqa: F401 — reserved for future cases

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration / session fixtures
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "connector_proxy.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    # Stable secret key so derive_signing_key on the verify side reproduces
    # the same per-pod key the test signs with.
    monkeypatch.setenv(
        "SECRET_KEY", "test-secret-key-for-connector-proxy-integration"
    )

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str, monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(
        "app.database.AsyncSessionLocal", maker, raising=False
    )

    async def _override_get_db():
        async with maker() as session:
            yield session

    # Patch the FastAPI Depends(get_db) the connector_proxy router uses.
    monkeypatch.setattr(
        "app.database.get_db", _override_get_db, raising=False
    )

    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"proxy-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Proxy Test User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_app_install_with_slack_grant(
    db, *, owner_user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed AppInstance + AppConnectorRequirement + AppConnectorGrant
    with an attached McpOAuthConnection holding an encrypted Slack token.

    Returns ``(app_instance_id, oauth_connection_id, requirement_id)``.

    The marketplace_apps + app_versions FK chain is heavyweight; we
    insert minimal rows so the FK constraints are satisfied without
    pulling in the full app-publish flow.
    """
    from sqlalchemy import insert as core_insert

    # Minimal MarketplaceApp + AppVersion to satisfy FKs on AppInstance.
    from app.models import (
        AppVersion,
        MarketplaceApp,
        UserMcpConfig,
    )
    from app.models_automations import (
        AppConnectorGrant,
        AppConnectorRequirement,
        AppInstance,
    )

    app_id = uuid.uuid4()
    db.add(
        MarketplaceApp(
            id=app_id,
            slug=f"slack-bot-{uuid.uuid4().hex[:6]}",
            handle=f"slack-bot-{uuid.uuid4().hex[:6]}",
            name="Slack Bot",
            description="test",
            category="productivity",
            state="published",
            creator_id=owner_user_id,
        )
    )

    app_version_id = uuid.uuid4()
    db.add(
        AppVersion(
            id=app_version_id,
            app_id=app_id,
            version="0.1.0",
            manifest_json={},
            bundle_address="cas://test",
            approval_state="approved",
        )
    )
    await db.flush()

    requirement_id = uuid.uuid4()
    db.add(
        AppConnectorRequirement(
            id=requirement_id,
            app_version_id=app_version_id,
            connector_id="slack",
            kind="oauth",
            scopes=["chat:write"],
            exposure="proxy",
        )
    )

    instance_id = uuid.uuid4()
    db.add(
        AppInstance(
            id=instance_id,
            app_id=app_id,
            app_version_id=app_version_id,
            installer_user_id=owner_user_id,
            state="active",
        )
    )
    await db.flush()

    # User MCP config + OAuth connection holding the encrypted token.
    from app.services.channels.registry import encrypt_credentials

    user_mcp_config_id = uuid.uuid4()
    db.add(
        UserMcpConfig(
            id=user_mcp_config_id,
            user_id=owner_user_id,
            server_id="slack",
            server_name="Slack",
            is_enabled=True,
        )
    )
    await db.flush()

    oauth_id = uuid.uuid4()
    encrypted = encrypt_credentials({"access_token": "xoxb-fake"})
    from app.models import McpOAuthConnection

    db.add(
        McpOAuthConnection(
            id=oauth_id,
            user_mcp_config_id=user_mcp_config_id,
            server_url="https://slack.com",
            tokens_encrypted=encrypted,
            client_info_encrypted=encrypt_credentials({"client_id": "x"}),
            registration_method="dcr",
        )
    )

    db.add(
        AppConnectorGrant(
            id=uuid.uuid4(),
            app_instance_id=instance_id,
            requirement_id=requirement_id,
            resolved_ref={"kind": "oauth_connection", "id": str(oauth_id)},
            exposure_at_grant="proxy",
            granted_by_user_id=owner_user_id,
        )
    )
    await db.commit()
    return instance_id, oauth_id, requirement_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proxy_call_succeeds_without_app_seeing_token(
    session_maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: app pod -> proxy -> upstream Slack, token never leaks.

    The mocked upstream captures the headers it received -- we assert
    Authorization: Bearer xoxb-fake landed on the upstream call. Then we
    assert the Authorization header was stripped from the response back
    to the app pod.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")

    import httpx
    from fastapi.testclient import TestClient

    from app.services.apps.connector_proxy.auth import (
        APP_INSTANCE_HEADER,
        derive_signing_key,
        generate_pod_token,
        invalidate_signing_key_cache,
    )

    # 1. Seed everything.
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        instance_id, _oauth_id, _req_id = (
            await _seed_app_install_with_slack_grant(db, owner_user_id=owner_id)
        )

    # 2. Mint the per-pod token using the same derivation the verifier uses.
    invalidate_signing_key_cache()
    signing_key = derive_signing_key(instance_id)
    token = generate_pod_token(
        app_instance_id=instance_id, signing_key=signing_key
    )

    # 3. Mock httpx.AsyncClient so we can capture the outbound call.
    captured_calls: list[dict[str, Any]] = []

    class _MockClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._kwargs = kwargs

        async def __aenter__(self) -> "_MockClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            params: dict[str, str] | None = None,
            content: bytes | None = None,
            **_: Any,
        ) -> httpx.Response:
            captured_calls.append(
                {
                    "method": method,
                    "url": url,
                    "headers": dict(headers or {}),
                    "params": dict(params or {}),
                    "content": content,
                }
            )
            return httpx.Response(
                status_code=200,
                content=json.dumps({"ok": True}).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    # Slack DOES echo Authorization back in some flows;
                    # the proxy must strip it before responding.
                    "authorization": "Bearer xoxb-fake",
                },
            )

    monkeypatch.setattr(
        "app.services.apps.connector_proxy.router.httpx.AsyncClient",
        _MockClient,
    )

    # 4. Build the test client and POST to the proxy.
    try:
        from app.main import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.main not importable: {exc!r}")

    body = json.dumps({"channel": "C123", "text": "hello"}).encode("utf-8")

    with TestClient(app, base_url="http://test") as client:
        resp = client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            content=body,
            headers={
                "Content-Type": "application/json",
                APP_INSTANCE_HEADER: token,
                # Try to smuggle an Authorization header — the proxy
                # MUST strip this before forwarding.
                "Authorization": "Bearer attacker-supplied",
            },
        )

    # 5. Status + outbound assertions.
    assert resp.status_code == 200, f"proxy returned {resp.status_code}: {resp.text!r}"
    assert len(captured_calls) == 1, (
        f"expected exactly one upstream call, got {len(captured_calls)}"
    )
    call = captured_calls[0]
    assert call["url"] == "https://slack.com/api/chat.postMessage", call["url"]
    # The injected Authorization header MUST carry the decrypted bearer.
    assert call["headers"].get("Authorization") == "Bearer xoxb-fake"
    # The smuggled Authorization from the app pod MUST be gone.
    assert "Bearer attacker-supplied" not in (
        call["headers"].get("Authorization") or ""
    )
    # The OpenSail auth header MUST NOT have been forwarded upstream.
    assert APP_INSTANCE_HEADER not in call["headers"]
    assert APP_INSTANCE_HEADER.lower() not in {
        k.lower() for k in call["headers"]
    }

    # 6. Response back to the pod must NOT carry Authorization.
    assert "authorization" not in {k.lower() for k in resp.headers}

    # 7. The body never carried the token.
    assert b"xoxb-fake" not in body
    # The request body the upstream saw is what the app pod sent:
    assert call["content"] == body

    # 8. Audit row was written.
    async with session_maker() as db:
        from app.models_automations import ConnectorProxyCall

        rows = (
            await db.execute(
                select(ConnectorProxyCall).where(
                    ConnectorProxyCall.app_instance_id == instance_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
    assert rows[0].status_code == 200
    assert rows[0].connector_id == "slack"
    assert rows[0].endpoint == "chat.postMessage"


@pytest.mark.integration
def test_oauth_plus_env_exposure_rejected_at_install() -> None:
    """Manifest validation refuses ``kind='oauth'`` + ``exposure='env'``.

    Handing a rotating OAuth token to the app process via env defeats
    rotation -- the manifest schema's ``ConnectorSpec2026`` model
    validator must raise on this combo.
    """
    from pydantic import ValidationError

    from app.services.apps.app_manifest import ConnectorSpec2026

    # Sanity: the safe combos parse cleanly.
    ConnectorSpec2026(id="slack", kind="oauth", exposure="proxy")
    ConnectorSpec2026(id="api", kind="api_key", exposure="env")

    with pytest.raises(ValidationError) as exc_info:
        ConnectorSpec2026(id="slack", kind="oauth", exposure="env")

    err_text = str(exc_info.value).lower()
    assert "oauth" in err_text
    assert "env" in err_text, (
        "validation error must explicitly mention 'env' so install-time "
        "callers can surface the right remediation"
    )
