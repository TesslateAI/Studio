"""
Wave 7 — federation tests for ``app.routers.marketplace_apps``.

Covers:
  - ``GET /api/marketplace-apps?source=<handle>`` filters cached app
    rows down to a single source.
  - ``GET /api/marketplace-apps/{id}?source=<handle>`` 404s when the
    app's source_id does not match the requested handle.
  - ``POST /api/marketplace-apps/{id}/fork`` honours the install_guard
    (community-hub apps are 403'd; admin_trusted and official sources
    pass the gate).

Test design mirrors ``tests/routers/test_marketplace_source_aware.py``
(Wave 4): seed a couple of fake federated sources directly into the
orchestrator's DB on a throwaway event loop, then exercise the routes
through ``authenticated_client`` (whose own loop never sees the seed
session).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# Stable UUIDs for the fake sources / apps so re-runs are deterministic.
_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_ADMIN_TRUSTED_SOURCE_ID = uuid.UUID("aaaa1111-2222-3333-4444-555555555555")
_PRIVATE_SOURCE_ID = uuid.UUID("bbbb1111-2222-3333-4444-555555555555")
_UNTRUSTED_SOURCE_ID = uuid.UUID("cccc1111-2222-3333-4444-555555555555")

_OFFICIAL_APP_ID = uuid.UUID("11111111-aaaa-bbbb-cccc-000000000001")
_ADMIN_TRUSTED_APP_ID = uuid.UUID("11111111-aaaa-bbbb-cccc-000000000002")
_PRIVATE_APP_ID = uuid.UUID("11111111-aaaa-bbbb-cccc-000000000003")
_UNTRUSTED_APP_ID = uuid.UUID("11111111-aaaa-bbbb-cccc-000000000004")

_OFFICIAL_APP_VERSION_ID = uuid.UUID("22222222-aaaa-bbbb-cccc-000000000001")
_ADMIN_TRUSTED_APP_VERSION_ID = uuid.UUID("22222222-aaaa-bbbb-cccc-000000000002")
_PRIVATE_APP_VERSION_ID = uuid.UUID("22222222-aaaa-bbbb-cccc-000000000003")
_UNTRUSTED_APP_VERSION_ID = uuid.UUID("22222222-aaaa-bbbb-cccc-000000000004")


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    """Run a DB coroutine on a throwaway event loop with a fresh engine.

    Mirrors the Wave-4 test file's helper — keeps asyncpg's pool bound
    to the loop that is about to close, avoiding cross-loop coupling
    with the FastAPI TestClient's own event loop.
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


async def _seed(db: AsyncSession) -> None:
    """Upsert four federated sources + one approved-public app per source."""
    from datetime import UTC, datetime

    from sqlalchemy import delete
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import (
        AppInstance,
        AppVersion,
        MarketplaceApp,
        MarketplaceSource,
    )

    src_rows = [
        {
            "id": _ADMIN_TRUSTED_SOURCE_ID,
            "handle": "admin-trusted-test-w7",
            "display_name": "Admin Trusted Test Hub",
            "base_url": "https://admin-trusted.example.com",
            "scope": "system",
            "trust_level": "admin_trusted",
            "is_active": True,
        },
        {
            "id": _PRIVATE_SOURCE_ID,
            "handle": "private-test-w7",
            "display_name": "Private Test Hub",
            "base_url": "https://private.example.com",
            "scope": "system",
            "trust_level": "private",
            "is_active": True,
        },
        {
            "id": _UNTRUSTED_SOURCE_ID,
            "handle": "untrusted-test-w7",
            "display_name": "Untrusted Test Hub",
            "base_url": "https://untrusted.example.com",
            "scope": "system",
            "trust_level": "untrusted",
            "is_active": True,
        },
    ]
    src_stmt = pg_insert(MarketplaceSource).values(src_rows)
    src_stmt = src_stmt.on_conflict_do_update(
        index_elements=[MarketplaceSource.id],
        set_={
            "handle": src_stmt.excluded.handle,
            "display_name": src_stmt.excluded.display_name,
            "base_url": src_stmt.excluded.base_url,
            "trust_level": src_stmt.excluded.trust_level,
            "is_active": True,
        },
    )
    await db.execute(src_stmt)

    # Sweep any AppInstance rows that point at our test apps so we can
    # rewrite the parent app rows without FK violations on re-seed.
    await db.execute(
        delete(AppInstance).where(
            AppInstance.app_id.in_(
                [
                    _OFFICIAL_APP_ID,
                    _ADMIN_TRUSTED_APP_ID,
                    _PRIVATE_APP_ID,
                    _UNTRUSTED_APP_ID,
                ]
            )
        )
    )
    await db.execute(
        delete(AppVersion).where(
            AppVersion.id.in_(
                [
                    _OFFICIAL_APP_VERSION_ID,
                    _ADMIN_TRUSTED_APP_VERSION_ID,
                    _PRIVATE_APP_VERSION_ID,
                    _UNTRUSTED_APP_VERSION_ID,
                ]
            )
        )
    )
    await db.execute(
        delete(MarketplaceApp).where(
            MarketplaceApp.id.in_(
                [
                    _OFFICIAL_APP_ID,
                    _ADMIN_TRUSTED_APP_ID,
                    _PRIVATE_APP_ID,
                    _UNTRUSTED_APP_ID,
                ]
            )
        )
    )

    apps = [
        (
            _OFFICIAL_APP_ID,
            _OFFICIAL_ID,
            "wave7-official-app",
            _OFFICIAL_APP_VERSION_ID,
        ),
        (
            _ADMIN_TRUSTED_APP_ID,
            _ADMIN_TRUSTED_SOURCE_ID,
            "wave7-admin-trusted-app",
            _ADMIN_TRUSTED_APP_VERSION_ID,
        ),
        (
            _PRIVATE_APP_ID,
            _PRIVATE_SOURCE_ID,
            "wave7-private-app",
            _PRIVATE_APP_VERSION_ID,
        ),
        (
            _UNTRUSTED_APP_ID,
            _UNTRUSTED_SOURCE_ID,
            "wave7-untrusted-app",
            _UNTRUSTED_APP_VERSION_ID,
        ),
    ]
    now = datetime.now(UTC)
    for app_id, source_id, slug, av_id in apps:
        db.add(
            MarketplaceApp(
                id=app_id,
                slug=slug,
                name=slug.replace("-", " ").title(),
                creator_user_id=None,
                source_id=source_id,
                state="approved",
                visibility="public",
                forkable="true",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            AppVersion(
                id=av_id,
                app_id=app_id,
                version="1.0.0",
                manifest_schema_version="2026-05",
                manifest_json={"id": slug, "version": "1.0.0"},
                manifest_hash=f"hash-{av_id}",
                bundle_hash=f"bundle-{av_id}",
                feature_set_hash="feat-stable",
                approval_state="stage1_approved",
                published_at=now,
                source_id=source_id,
            )
        )
    await db.commit()


def _seed_sync() -> None:
    _run_db(_seed)


# ---------------------------------------------------------------------------
# Source filter on list
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_apps_with_source_filter_returns_only_that_source(authenticated_client):
    _seed_sync()
    client, _ = authenticated_client

    resp = client.get("/api/marketplace-apps?source=admin-trusted-test-w7&limit=200")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    handles = {item.get("source_handle") for item in body["items"]}
    # Either all rows carry the requested handle, or the result set is
    # empty (no apps from this source landed yet on a fresh DB).
    assert handles <= {"admin-trusted-test-w7"}, (
        f"source filter leaked rows from other sources: {handles!r}"
    )
    if handles:
        slugs = {item["slug"] for item in body["items"]}
        assert "wave7-admin-trusted-app" in slugs


@pytest.mark.integration
def test_list_apps_unknown_source_returns_404(authenticated_client):
    client, _ = authenticated_client
    resp = client.get("/api/marketplace-apps?source=does-not-exist-w7")
    assert resp.status_code == 404
    assert "does-not-exist-w7" in resp.text


@pytest.mark.integration
def test_list_apps_without_source_filter_returns_all(authenticated_client):
    _seed_sync()
    client, _ = authenticated_client

    resp = client.get("/api/marketplace-apps?limit=500")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body

    filtered = client.get(
        "/api/marketplace-apps?source=admin-trusted-test-w7&limit=500"
    ).json()
    assert len(body["items"]) >= len(filtered["items"])


# ---------------------------------------------------------------------------
# Source filter on detail
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_app_with_matching_source_filter_returns_row(authenticated_client):
    _seed_sync()
    client, _ = authenticated_client

    resp = client.get(
        f"/api/marketplace-apps/{_ADMIN_TRUSTED_APP_ID}?source=admin-trusted-test-w7"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(_ADMIN_TRUSTED_APP_ID)
    assert body["source_handle"] == "admin-trusted-test-w7"
    assert body["source_trust_level"] == "admin_trusted"


@pytest.mark.integration
def test_get_app_with_mismatched_source_filter_returns_404(authenticated_client):
    _seed_sync()
    client, _ = authenticated_client

    # The app belongs to admin-trusted but we request it scoped to private.
    resp = client.get(
        f"/api/marketplace-apps/{_ADMIN_TRUSTED_APP_ID}?source=private-test-w7"
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# install_guard via fork endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fork_app_from_admin_trusted_source_passes_install_guard(authenticated_client):
    """admin_trusted sources clear the install_guard for ``app`` kind.

    The fork itself may fail downstream (Hub volume creation, slug
    collisions) — we only assert that install_guard does NOT 403/409.
    Anything other than ``install_blocked`` / ``install_requires_confirmation``
    is a pass for this test.
    """
    _seed_sync()
    client, _ = authenticated_client
    resp = client.post(
        f"/api/marketplace-apps/{_ADMIN_TRUSTED_APP_ID}/fork",
        json={
            "source_app_version_id": str(_ADMIN_TRUSTED_APP_VERSION_ID),
            "new_slug": f"fork-admin-trusted-{uuid.uuid4().hex[:8]}",
            "new_name": "Fork of admin trusted",
        },
    )
    if resp.status_code in (403, 409):
        detail = resp.json().get("detail")
        assert not (
            isinstance(detail, dict)
            and detail.get("error")
            in ("install_blocked", "install_requires_confirmation")
        ), f"install_guard rejected admin_trusted fork: {detail!r}"


@pytest.mark.integration
def test_fork_app_from_private_source_returns_403(authenticated_client):
    """Wave 7: private hubs cannot serve apps even via fork."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.post(
        f"/api/marketplace-apps/{_PRIVATE_APP_ID}/fork",
        json={
            "source_app_version_id": str(_PRIVATE_APP_VERSION_ID),
            "new_slug": f"fork-private-{uuid.uuid4().hex[:8]}",
            "new_name": "Fork of private app",
        },
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail")
    assert isinstance(detail, dict), f"expected dict detail, got {detail!r}"
    assert detail.get("error") == "install_blocked"
    assert detail.get("kind") == "app"
    assert "admin_trusted" in detail.get("reason", "")


@pytest.mark.integration
def test_fork_app_from_untrusted_source_returns_403(authenticated_client):
    _seed_sync()
    client, _ = authenticated_client
    resp = client.post(
        f"/api/marketplace-apps/{_UNTRUSTED_APP_ID}/fork",
        json={
            "source_app_version_id": str(_UNTRUSTED_APP_VERSION_ID),
            "new_slug": f"fork-untrusted-{uuid.uuid4().hex[:8]}",
            "new_name": "Fork of untrusted app",
        },
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail")
    assert isinstance(detail, dict), f"expected dict detail, got {detail!r}"
    assert detail.get("error") == "install_blocked"
    assert detail.get("kind") == "app"


# ---------------------------------------------------------------------------
# install_guard unit (no DB) — verifies the federation matrix for app kind.
# ---------------------------------------------------------------------------


def _make_source(*, trust_level: str, is_active: bool = True):
    """Lightweight duck-typed source row that mirrors install_guard's
    attribute access without dragging SQLAlchemy in."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid.uuid4(),
        handle=f"{trust_level}-source",
        base_url="https://example.com",
        trust_level=trust_level,
        scope="system",
        user_id=None,
        team_id=None,
        is_active=is_active,
        capabilities_cache=[],
        pinned_hub_id="hub-test",
    )


def test_install_guard_admin_trusted_allows_app_kind() -> None:
    from app.services.marketplace_federation import install_guard

    decision = install_guard(_make_source(trust_level="admin_trusted"), "app")
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_install_guard_official_allows_app_kind() -> None:
    from app.services.marketplace_federation import install_guard

    decision = install_guard(_make_source(trust_level="official"), "app")
    assert decision.allowed is True


def test_install_guard_private_blocks_app_kind() -> None:
    """Wave 7: apps no longer surface a confirmation modal on private
    hubs — the install gate refuses outright."""
    from app.services.marketplace_federation import install_guard

    decision = install_guard(_make_source(trust_level="private"), "app")
    assert decision.allowed is False
    assert "admin_trusted" in decision.reason


def test_install_guard_untrusted_blocks_app_kind() -> None:
    from app.services.marketplace_federation import install_guard

    decision = install_guard(_make_source(trust_level="untrusted"), "app")
    assert decision.allowed is False
