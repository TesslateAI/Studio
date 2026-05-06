"""
Wave 5 — ``/api/marketplace/sources`` CRUD router tests.

Exercises the full source registry surface against a real Postgres test
DB:

  - GET    /api/marketplace/sources               (list visible)
  - POST   /api/marketplace/sources               (create user/team)
  - PATCH  /api/marketplace/sources/{id}          (update)
  - DELETE /api/marketplace/sources/{id}          (soft-delete)
  - POST   /api/marketplace/sources/{id}/test     (pin hub_id)
  - POST   /api/marketplace/sources/{id}/sync     (run worker)
  - POST   /api/marketplace/sources/{id}/promote  (superuser)

Coverage:

  * Anonymous list returns the two seeded system rows.
  * Auto-trust classification: no token → ``untrusted``, with token →
    ``private``. Superuser /promote can flip to ``admin_trusted``.
  * Visibility scoping: user A cannot see user B's source.
  * System row immutability: PATCH/DELETE return 403.
  * Validation: ``local://`` rejected, https-only enforced in production.
  * /test endpoint pins ``hub_id`` and snapshots capabilities/policies
    against a stubbed httpx transport.
  * /sync endpoint invokes the worker and returns the per-source result.
  * /promote requires superuser.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    """Run a DB coroutine on a throwaway loop with a fresh engine.

    Same pattern used by other Wave-4/5 tests to avoid the
    ``Future attached to a different loop`` error caused by sharing
    the app's AsyncSessionLocal pool with the TestClient's loop.
    """

    async def _inner():
        engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Helpers — register a fresh user, return an authed client + user_id
# ---------------------------------------------------------------------------


def _register_user(api_client_session) -> tuple[Any, str]:
    """Register a brand-new user via /api/auth/register and return (client, user_id).

    Sets the Authorization header on the shared session client.
    """
    email = f"src-test-{uuid4().hex}@example.com"
    register_payload = {
        "email": email,
        "password": "TestPassword123!",
        "name": "Sources Router Test User",
    }
    resp = api_client_session.post("/api/auth/register", json=register_payload)
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]
    login_resp = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email, "password": register_payload["password"]},
    )
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]
    api_client_session.headers["Authorization"] = f"Bearer {token}"
    return api_client_session, user_id


# ---------------------------------------------------------------------------
# List / system rows
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_returns_at_least_the_system_rows(authenticated_client):
    """Authenticated requester sees the two seeded system rows."""
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/sources")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    handles = {r["handle"] for r in rows}
    assert "tesslate-official" in handles
    assert "local" in handles
    for r in rows:
        if r["handle"] in {"tesslate-official", "local"}:
            assert r["is_system"] is True
            assert r["scope"] == "system"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_user_source_without_token_is_untrusted(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-untrusted-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Untrusted Test Hub",
            "base_url": "https://untrusted.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trust_level"] == "untrusted"
    assert body["scope"] == "user"
    assert body["has_token"] is False
    assert body["is_active"] is True


@pytest.mark.integration
def test_create_user_source_with_token_is_private(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-private-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Private Test Hub",
            "base_url": "https://private.example.com",
            "encrypted_token": "secret-bearer-token",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trust_level"] == "private"
    assert body["has_token"] is True
    # The encrypted token is never returned in any response field.
    for k, v in body.items():
        assert "secret-bearer-token" not in str(v), (
            f"Plaintext token leaked in response field {k!r}: {v!r}"
        )


@pytest.mark.integration
def test_create_rejects_local_scheme(authenticated_client):
    client, _ = authenticated_client
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": "should-fail",
            "display_name": "Should Fail",
            "base_url": "local://drafts/user/me",
            "scope": "user",
        },
    )
    assert resp.status_code == 422
    assert "local" in resp.text.lower()


@pytest.mark.integration
def test_create_rejects_reserved_handles(authenticated_client):
    client, _ = authenticated_client
    for reserved in ("tesslate-official", "local"):
        resp = client.post(
            "/api/marketplace/sources",
            json={
                "handle": reserved,
                "display_name": "Imposter",
                "base_url": "https://imposter.example.com",
                "scope": "user",
            },
        )
        assert resp.status_code == 422, f"{reserved!r} accepted: {resp.text}"


@pytest.mark.integration
def test_create_rejects_invalid_handle_chars(authenticated_client):
    client, _ = authenticated_client
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": "has spaces",
            "display_name": "Bad Handle",
            "base_url": "https://x.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_create_rejects_http_in_production(authenticated_client, monkeypatch):
    """In production HTTP is forbidden except for localhost loopback."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "deployment_env", "production")

    client, _ = authenticated_client
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": f"prod-http-{uuid4().hex[:6]}",
            "display_name": "Bad",
            "base_url": "http://insecure.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 422

    # localhost loopback is allowed even in production.
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": f"prod-localhost-{uuid4().hex[:6]}",
            "display_name": "Localhost OK",
            "base_url": "http://localhost:8800",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
def test_create_user_handle_collision_returns_409(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-dup-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "First",
            "base_url": "https://x.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Second",
            "base_url": "https://y.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Visibility scoping (cross-user isolation)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_user_cannot_see_other_users_source(api_client_session):
    """Cross-user visibility: user A creates a source; user B cannot list
    or PATCH/DELETE/test/sync it."""
    # User A creates a source.
    client_a, user_a_id = _register_user(api_client_session)
    handle = f"a-private-{uuid4().hex[:6]}"
    resp = client_a.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "A's Source",
            "base_url": "https://a.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["id"]
    api_client_session.headers.pop("Authorization", None)

    # User B can't see it.
    client_b, user_b_id = _register_user(api_client_session)
    assert user_a_id != user_b_id
    listing = client_b.get("/api/marketplace/sources").json()
    assert all(r["id"] != source_id for r in listing), (
        "User B saw user A's source in /api/marketplace/sources"
    )
    # Direct hits return 404 (not 403 — consistent with "doesn't exist for me").
    for verb, kwargs in (
        ("get", {}),
        ("patch", {"json": {"display_name": "Hijack"}}),
        ("delete", {}),
        ("post", {"url_suffix": "/test"}),
        ("post", {"url_suffix": "/sync"}),
    ):
        url_suffix = kwargs.pop("url_suffix", "")
        url = f"/api/marketplace/sources/{source_id}{url_suffix}"
        # GET on a single resource isn't exposed; we test PATCH/DELETE/POST.
        if verb == "get":
            continue
        resp = getattr(client_b, verb)(url, **kwargs)
        assert resp.status_code == 404, (
            f"{verb.upper()} {url} from user B got {resp.status_code} (expected 404)"
        )

    api_client_session.headers.pop("Authorization", None)


# ---------------------------------------------------------------------------
# Update + system row immutability
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_patch_system_row_returns_403(authenticated_client):
    client, _ = authenticated_client
    rows = client.get("/api/marketplace/sources").json()
    sys_row = next(r for r in rows if r["handle"] == "tesslate-official")
    resp = client.patch(
        f"/api/marketplace/sources/{sys_row['id']}",
        json={"display_name": "Hacker"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
def test_delete_system_row_returns_403(authenticated_client):
    client, _ = authenticated_client
    rows = client.get("/api/marketplace/sources").json()
    sys_row = next(r for r in rows if r["handle"] == "tesslate-official")
    resp = client.delete(f"/api/marketplace/sources/{sys_row['id']}")
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
def test_patch_user_source_updates_display_and_token(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-edit-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Original",
            "base_url": "https://x.example.com",
            "scope": "user",
        },
    )
    sid = resp.json()["id"]
    assert resp.json()["trust_level"] == "untrusted"

    # Adding a token flips trust to private.
    resp = client.patch(
        f"/api/marketplace/sources/{sid}",
        json={"display_name": "Renamed", "encrypted_token": "new-token"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Renamed"
    assert body["has_token"] is True
    assert body["trust_level"] == "private"

    # Clearing the token reverts trust to untrusted.
    resp = client.patch(
        f"/api/marketplace/sources/{sid}",
        json={"clear_token": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_token"] is False
    assert body["trust_level"] == "untrusted"


@pytest.mark.integration
def test_soft_delete_sets_inactive(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-del-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "To Delete",
            "base_url": "https://x.example.com",
            "scope": "user",
        },
    )
    sid = resp.json()["id"]
    resp = client.delete(f"/api/marketplace/sources/{sid}")
    assert resp.status_code == 204
    # Default list excludes inactive rows for non-system scope.
    listing = client.get("/api/marketplace/sources").json()
    assert all(r["id"] != sid for r in listing)
    listing = client.get("/api/marketplace/sources?include_inactive=true").json()
    assert any(r["id"] == sid and r["is_active"] is False for r in listing)


# ---------------------------------------------------------------------------
# /test endpoint — hub_id pinning + capability snapshot
# ---------------------------------------------------------------------------


_FAKE_HUB_MANIFEST = {
    "hub_id": "00000000-1111-2222-3333-444444444444",
    "api_version": "v1",
    "display_name": "Wave 5 Test Hub",
    "build_revision": "test-rev-001",
    "capabilities": ["catalog.read", "catalog.changes", "bundles.signed_url"],
    "policies": {"requires_signed_bundles": False},
}


def _stub_marketplace_client_factory(manifest=_FAKE_HUB_MANIFEST):
    """Build a MockTransport that returns ``manifest`` with the right
    X-Tesslate-Hub-Id header for any /v1/manifest GET."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/manifest"):
            return httpx.Response(
                200,
                json=manifest,
                headers={
                    "X-Tesslate-Hub-Id": manifest["hub_id"],
                    "X-Tesslate-Hub-Api-Version": manifest.get("api_version", "v1"),
                },
            )
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.MockTransport(_handler)


@pytest.mark.integration
def test_test_endpoint_pins_hub_id_and_caches_manifest(authenticated_client):
    from app.services import marketplace_client as mc

    client, _ = authenticated_client
    handle = f"u-test-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Test Connection Hub",
            "base_url": "https://wave5-test-hub.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    assert resp.json()["pinned_hub_id"] is None

    # Patch httpx.AsyncClient inside MarketplaceClient so the /v1/manifest
    # call hits the MockTransport. The simplest interception point is to
    # patch ``httpx.AsyncClient`` itself for the duration of the call.
    transport = _stub_marketplace_client_factory()
    real_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    with patch.object(mc.httpx, "AsyncClient", _patched_async_client):
        resp = client.post(f"/api/marketplace/sources/{sid}/test")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hub_id"] == _FAKE_HUB_MANIFEST["hub_id"]
    assert body["pinned_hub_id_changed"] is True
    assert "catalog.read" in body["capabilities"]
    assert body["policies"] == _FAKE_HUB_MANIFEST["policies"]
    assert body["display_name"] == _FAKE_HUB_MANIFEST["display_name"]
    # Trust auto-classified to untrusted (no token).
    assert body["auto_trust_level"] == "untrusted"

    # Verify the row is now pinned + capabilities cached.
    listing = client.get("/api/marketplace/sources").json()
    pinned = next(r for r in listing if r["id"] == sid)
    assert pinned["pinned_hub_id"] == _FAKE_HUB_MANIFEST["hub_id"]
    assert "catalog.read" in pinned["capabilities"]


# ---------------------------------------------------------------------------
# /sync endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sync_endpoint_returns_per_source_result(authenticated_client):
    """The /sync endpoint runs the worker. We patch the worker's
    sync_source method so the test doesn't need a live marketplace."""
    client, _ = authenticated_client
    handle = f"u-sync-{uuid4().hex[:6]}"
    resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Sync Hub",
            "base_url": "https://wave5-sync-hub.example.com",
            "scope": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]

    from app.services import marketplace_sync as msync

    async def _fake_sync_source(self, source_id):
        return msync.SyncResult(
            source_id=source_id,
            source_handle=handle,
            items_upserted=2,
            items_deleted=0,
            events_processed=2,
            etag_advanced_to="v42",
        )

    with patch.object(msync.MarketplaceSyncWorker, "sync_source", _fake_sync_source):
        resp = client.post(f"/api/marketplace/sources/{sid}/sync")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["events_processed"] == 2
    assert body["items_upserted"] == 2
    assert body["etag_advanced_to"] == "v42"
    assert body["source_handle"] == handle
    assert body["error"] is None


@pytest.mark.integration
def test_sync_inactive_source_returns_409(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-inactive-{uuid4().hex[:6]}"
    create_resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Inactive Hub",
            "base_url": "https://inactive.example.com",
            "scope": "user",
        },
    )
    sid = create_resp.json()["id"]
    client.patch(f"/api/marketplace/sources/{sid}", json={"is_active": False})
    resp = client.post(f"/api/marketplace/sources/{sid}/sync")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# /promote endpoint (superuser only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_promote_requires_superuser(authenticated_client):
    client, _ = authenticated_client
    handle = f"u-promote-{uuid4().hex[:6]}"
    create_resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "To Promote",
            "base_url": "https://promote.example.com",
            "scope": "user",
        },
    )
    sid = create_resp.json()["id"]
    resp = client.post(
        f"/api/marketplace/sources/{sid}/promote",
        json={"trust_level": "admin_trusted"},
    )
    # Non-superuser → 401 (fastapi-users superuser guard).
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_promote_as_superuser_flips_trust_level(authenticated_client):
    client, user_data = authenticated_client
    handle = f"u-promote-ok-{uuid4().hex[:6]}"
    create_resp = client.post(
        "/api/marketplace/sources",
        json={
            "handle": handle,
            "display_name": "Promote Target",
            "base_url": "https://promote-ok.example.com",
            "scope": "user",
        },
    )
    sid = create_resp.json()["id"]
    assert create_resp.json()["trust_level"] == "untrusted"

    # Flip the requester to superuser at the DB layer for this test.
    async def _flip(db):
        from sqlalchemy import update

        from app.models import User

        await db.execute(
            update(User).where(User.id == uuid.UUID(user_data["id"])).values(is_superuser=True)
        )
        await db.commit()

    _run_db(_flip)

    resp = client.post(
        f"/api/marketplace/sources/{sid}/promote",
        json={"trust_level": "admin_trusted"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trust_level"] == "admin_trusted"

    # Demote back works too.
    resp = client.post(
        f"/api/marketplace/sources/{sid}/promote",
        json={"trust_level": "untrusted"},
    )
    assert resp.status_code == 200
    assert resp.json()["trust_level"] == "untrusted"


@pytest.mark.integration
def test_promote_system_row_returns_403(authenticated_client):
    client, user_data = authenticated_client

    # Make superuser.
    async def _flip(db):
        from sqlalchemy import update

        from app.models import User

        await db.execute(
            update(User).where(User.id == uuid.UUID(user_data["id"])).values(is_superuser=True)
        )
        await db.commit()

    _run_db(_flip)

    rows = client.get("/api/marketplace/sources").json()
    sys_row = next(r for r in rows if r["handle"] == "tesslate-official")
    resp = client.post(
        f"/api/marketplace/sources/{sys_row['id']}/promote",
        json={"trust_level": "untrusted"},
    )
    assert resp.status_code == 403, resp.text
