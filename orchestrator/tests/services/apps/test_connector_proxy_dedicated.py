"""Phase 4: Connector Proxy as a dedicated ``opensail-runtime`` Deployment.

These tests pin the contract that lets us flip the proxy between the
embedded mount (desktop / docker-compose) and the standalone Deployment
(K8s) without touching app code:

* The ``__main__`` entrypoint constructs a FastAPI app with the proxy
  router mounted and a ``/health`` endpoint.
* ``CONNECTOR_PROXY_MODE=embedded`` → orchestrator's ``main.py`` mounts
  the router at ``/api/v1/connector-proxy``.
* ``CONNECTOR_PROXY_MODE=dedicated`` → orchestrator does NOT mount the
  router; the standalone app is the only surface that serves it.
* The signed ``X-OpenSail-AppInstance`` header verifies the same way
  whether the request hits the embedded mount or the dedicated app.
* The installer's pod-template env dict layers ``OPENSAIL_RUNTIME_URL``
  and ``OPENSAIL_APPINSTANCE_TOKEN`` so the SDK inside the pod can find
  the proxy with a verifiable token.

We do NOT exercise the orchestrator boot path twice — once is enough to
prove the gate works.  The standalone app is built via its public
``create_app`` factory so a single test can inspect both shapes.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Importing models + models_automations registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.config import get_settings
from app.database import Base, get_db
from app.services.apps.connector_proxy.auth import (
    APP_INSTANCE_HEADER,
    derive_signing_key,
    generate_pod_token,
    invalidate_signing_key_cache,
)
from app.services.apps.env_resolver import resolve_env_for_pod


# ---------------------------------------------------------------------------
# Helpers — borrow the seed shape from test_connector_proxy.py.  We keep an
# inline copy rather than importing across test modules so the dedicated
# wave can evolve its own seed contract without snapping the embedded path.
# ---------------------------------------------------------------------------


def _signed_appinstance_header(instance_id: uuid.UUID) -> str:
    invalidate_signing_key_cache(instance_id)
    secret = (get_settings().secret_key or "test-secret").encode()
    key = derive_signing_key(instance_id, fallback_secret=secret.decode())
    return generate_pod_token(app_instance_id=instance_id, signing_key=key)


@pytest_asyncio.fixture
async def db_engine():
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
    maker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        yield session


@pytest.fixture
def dedicated_client(db_engine) -> Generator[TestClient, None, None]:
    """Test client wrapping the dedicated-mode standalone FastAPI app.

    Built via ``create_app()`` exactly as the K8s entrypoint runs it,
    with ``get_db`` overridden to point at the in-memory engine so we
    don't need Postgres.
    """
    from app.services.apps.connector_proxy.main import create_app

    maker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _get_test_db():
        async with maker() as session:
            try:
                yield session
            finally:
                await session.close()

    standalone = create_app()
    standalone.dependency_overrides[get_db] = _get_test_db

    with TestClient(standalone) as tc:
        yield tc


async def _seed_oauth_install(
    db: AsyncSession,
    *,
    connector_id: str = "slack",
    access_token: str = "xoxb-fake-test-token-1234567890ab",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Minimal seed: User → MarketplaceApp → AppVersion → AppInstance →
    AppConnectorRequirement → McpOAuthConnection → AppConnectorGrant.

    Returns ``(app_instance_id, oauth_connection_id)``.  Mirrors the
    embedded-path seed in ``test_connector_proxy.py``.
    """
    from app.models import (
        AppVersion,
        MarketplaceApp,
        McpOAuthConnection,
        User,
        UserMcpConfig,
    )
    from app.models_automations import (
        AppConnectorGrant,
        AppConnectorRequirement,
        AppInstance,
    )
    from app.services.channels.registry import encrypt_credentials

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

    grant = AppConnectorGrant(
        id=uuid.uuid4(),
        app_instance_id=instance.id,
        requirement_id=requirement.id,
        resolved_ref={"kind": "oauth_connection", "id": str(oauth.id)},
        exposure_at_grant="proxy",
        granted_by_user_id=user.id,
    )
    db.add(grant)

    await db.commit()
    return instance.id, oauth.id


# ---------------------------------------------------------------------------
# 1. Standalone app shape — the K8s entrypoint must build a real app.
# ---------------------------------------------------------------------------


def test_create_app_returns_fastapi_with_router_and_health() -> None:
    """``__main__`` calls ``create_app()`` — the result must be wired up."""
    from app.services.apps.connector_proxy.main import create_app

    standalone = create_app()
    assert isinstance(standalone, FastAPI)

    routes = {r.path for r in standalone.routes}
    # Health probe target — kubelet hits this every few seconds.
    assert "/health" in routes
    # Proxy router carries its own ``/api/v1/connector-proxy`` prefix.
    proxy_routes = [
        r for r in standalone.routes if "/connector-proxy/" in str(r.path)
    ]
    assert proxy_routes, (
        "create_app() must mount the connector_proxy router; got routes="
        f"{sorted(routes)}"
    )


def test_health_endpoint_returns_mode() -> None:
    """``/health`` reports the configured ``CONNECTOR_PROXY_MODE``.

    Cheap to exercise and gives operators a one-shot way to verify the
    pod actually flipped to dedicated mode.
    """
    from app.services.apps.connector_proxy.main import create_app

    standalone = create_app()
    with TestClient(standalone) as tc:
        resp = tc.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("status") == "ok"
    assert payload.get("service") == "opensail-runtime"
    # Mode is whichever the test environment is set to. Real assertion is
    # just that the field exists and is a string.
    assert isinstance(payload.get("mode"), str)


def test_main_module_exposes_main_callable() -> None:
    """``python -m app.services.apps.connector_proxy`` must have a main()."""
    mod = importlib.import_module("app.services.apps.connector_proxy.__main__")
    assert hasattr(mod, "main"), (
        "__main__ must expose a main() callable for the K8s entrypoint"
    )
    # Don't actually run it — that would block on uvicorn.run().


# ---------------------------------------------------------------------------
# 2. Mount-gate behavior on the orchestrator main.py.
# ---------------------------------------------------------------------------


def _orchestrator_proxy_routes() -> set[str]:
    """Return the set of orchestrator routes that match /connector-proxy/."""
    # Re-import main fresh so the module-level ``settings`` snapshot picks
    # up the patched env. We can't reuse a cached app between tests with
    # different CONNECTOR_PROXY_MODE values.
    import sys

    for mod_name in list(sys.modules):
        if mod_name.startswith("app.main"):
            del sys.modules[mod_name]
    get_settings.cache_clear()

    main_mod = importlib.import_module("app.main")
    return {
        str(r.path)
        for r in main_mod.app.routes
        if "/connector-proxy/" in str(r.path)
    }


def test_embedded_mode_mounts_router_on_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default / embedded mode → orchestrator exposes the proxy router."""
    monkeypatch.setenv("CONNECTOR_PROXY_MODE", "embedded")
    routes = _orchestrator_proxy_routes()
    assert routes, (
        "embedded mode must mount the proxy router on the orchestrator; "
        f"got no /connector-proxy/ routes among orchestrator routes"
    )


def test_dedicated_mode_skips_router_on_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedicated mode → orchestrator does NOT mount the proxy router.

    Pods must reach the proxy via the standalone Service; if the
    orchestrator also exposed it we'd defeat the NetworkPolicy boundary.
    """
    monkeypatch.setenv("CONNECTOR_PROXY_MODE", "dedicated")
    try:
        routes = _orchestrator_proxy_routes()
    finally:
        # Reset so subsequent tests don't see the dedicated module cache.
        monkeypatch.setenv("CONNECTOR_PROXY_MODE", "embedded")
        _orchestrator_proxy_routes()  # rebuild with embedded
    assert not routes, (
        "dedicated mode must NOT mount the proxy router on the "
        f"orchestrator; got {sorted(routes)}"
    )


def test_runtime_url_property_picks_dedicated_when_dedicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``connector_proxy_runtime_url`` is what the installer injects.

    Dedicated → ``http://opensail-runtime:8400``; embedded → orchestrator
    Service path. App pods read this through ``OPENSAIL_RUNTIME_URL``.
    """
    monkeypatch.setenv("CONNECTOR_PROXY_MODE", "dedicated")
    get_settings.cache_clear()
    s = get_settings()
    assert s.is_connector_proxy_dedicated is True
    assert s.connector_proxy_runtime_url == "http://opensail-runtime:8400"

    monkeypatch.setenv("CONNECTOR_PROXY_MODE", "embedded")
    get_settings.cache_clear()
    s = get_settings()
    assert s.is_connector_proxy_dedicated is False
    assert s.connector_proxy_runtime_url.endswith("/api/v1/connector-proxy")


# ---------------------------------------------------------------------------
# 3. Auth path — the dedicated app accepts X-OpenSail-AppInstance.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedicated_app_accepts_signed_appinstance_header(
    dedicated_client: TestClient, db_session: AsyncSession
) -> None:
    """The standalone app verifies the signed header end-to-end.

    Mirrors the embedded-path happy test: seed a Slack OAuth grant,
    mock the upstream, prove the proxy injected the bearer and stripped
    the smuggled Authorization on the way out.
    """
    token = "xoxb-fake-test-token-dedicated"
    instance_id, _ = await _seed_oauth_install(
        db_session, access_token=token
    )

    captured: dict[str, object] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "ts": "5.0"})

    with respx.mock(assert_all_called=True) as router:
        router.post("https://slack.com/api/chat.postMessage").mock(
            side_effect=_record
        )
        resp = dedicated_client.post(
            "/api/v1/connector-proxy/connectors/slack/chat.postMessage",
            headers={
                APP_INSTANCE_HEADER: _signed_appinstance_header(instance_id),
                "Content-Type": "application/json",
                # Smuggled by the app pod — proxy must strip before forwarding.
                "Authorization": "Bearer rogue-app-token",
            },
            json={"channel": "C123", "text": "hi from dedicated"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "ts": "5.0"}

    # Bearer was injected by the dedicated proxy.
    assert captured["headers"].get("authorization") == f"Bearer {token}"
    # Smuggled Authorization was stripped.
    assert "rogue-app-token" not in captured["headers"].get("authorization", "")
    # OpenSail header was stripped from the upstream call.
    assert "x-opensail-appinstance" not in {
        k.lower() for k in captured["headers"]  # type: ignore[union-attr]
    }


def test_dedicated_app_rejects_missing_header(
    dedicated_client: TestClient,
) -> None:
    """Same auth contract as the embedded path: 401 on missing header."""
    resp = dedicated_client.post(
        "/api/v1/connector-proxy/connectors/slack/chat.postMessage"
    )
    assert resp.status_code == 401
    assert APP_INSTANCE_HEADER in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Pod-template env injection — installer overlay shape.
# ---------------------------------------------------------------------------


def test_pod_env_includes_runtime_url_in_dedicated_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env overlay the installer layers on the primary container
    must carry ``OPENSAIL_RUNTIME_URL`` pointing at ``opensail-runtime``
    when ``CONNECTOR_PROXY_MODE=dedicated``."""
    monkeypatch.setenv("CONNECTOR_PROXY_MODE", "dedicated")
    get_settings.cache_clear()
    settings = get_settings()
    assert (
        settings.connector_proxy_runtime_url
        == "http://opensail-runtime:8400"
    )

    # Mirror what the installer puts on the Container row (see
    # services/apps/installer.py::install_app — runtime_env_overlay).
    container_env = {
        "OPENSAIL_RUNTIME_URL": settings.connector_proxy_runtime_url,
        "OPENSAIL_APPINSTANCE_TOKEN": (
            "${secret:app-pod-key-00000000-0000-0000-0000-000000000001/token}"
        ),
    }

    resolved = resolve_env_for_pod(container_env)
    by_name = {ev.name: ev for ev in resolved}

    # Runtime URL is a literal value the pod can read directly.
    assert "OPENSAIL_RUNTIME_URL" in by_name
    runtime_var = by_name["OPENSAIL_RUNTIME_URL"]
    assert runtime_var.value == "http://opensail-runtime:8400"
    assert runtime_var.value_from is None

    # Token is a secretKeyRef so the bytes never sit in the pod spec.
    assert "OPENSAIL_APPINSTANCE_TOKEN" in by_name
    token_var = by_name["OPENSAIL_APPINSTANCE_TOKEN"]
    assert token_var.value is None
    assert token_var.value_from is not None
    assert token_var.value_from.secret_key_ref is not None
    assert token_var.value_from.secret_key_ref.name == (
        "app-pod-key-00000000-0000-0000-0000-000000000001"
    )
    assert token_var.value_from.secret_key_ref.key == "token"


def test_pod_env_uses_orchestrator_path_in_embedded_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedded mode keeps the ``OPENSAIL_RUNTIME_URL`` env var pointing
    at the orchestrator's mounted router so desktop / docker keeps
    working without a second process.
    """
    monkeypatch.setenv("CONNECTOR_PROXY_MODE", "embedded")
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.is_connector_proxy_dedicated is False
    url = settings.connector_proxy_runtime_url
    assert url.endswith("/api/v1/connector-proxy"), url

    # The pod env still carries the same key — only the value differs.
    resolved = resolve_env_for_pod({"OPENSAIL_RUNTIME_URL": url})
    assert resolved[0].name == "OPENSAIL_RUNTIME_URL"
    assert resolved[0].value == url


# ---------------------------------------------------------------------------
# 5. Sanity: keep the rest-of-the-suite assumption that
# ``app.services.apps.connector_proxy.main:app`` is import-safe.
# ---------------------------------------------------------------------------


def test_module_attribute_app_is_a_fastapi_instance() -> None:
    """``main:app`` is the alternate uvicorn target.  Must exist + be a
    FastAPI instance for ``uvicorn app...connector_proxy.main:app``."""
    from app.services.apps.connector_proxy import main as proxy_main

    assert isinstance(proxy_main.app, FastAPI)
    # Also covers the docstring's promise: factory is exposed.
    assert callable(proxy_main.create_app)
    # The two are independent instances — calling create_app() again
    # mints a fresh app, so module-level ``app`` is the canonical one.
    second = proxy_main.create_app()
    assert second is not proxy_main.app
