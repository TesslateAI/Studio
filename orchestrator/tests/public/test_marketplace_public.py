"""Anonymous marketplace browse router (/api/marketplace/public)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models  # noqa: F401 — register ORM models


def _empty_catalog_db() -> AsyncMock:
    """AsyncMock db serving a browse query against an empty catalog:
    source-handle lookup (None) -> count (0) -> rows ([])."""
    src = MagicMock()
    src.scalar_one_or_none.return_value = None
    count = MagicMock()
    count.scalar_one.return_value = 0
    rows = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    rows.scalars.return_value = scalars

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[src, count, rows])
    return db


@pytest.fixture
def client() -> TestClient:
    from app.database import get_db
    from app.routers import marketplace_public

    marketplace_public._BUCKETS.clear()

    app = FastAPI()
    app.include_router(marketplace_public.router)

    async def _override_db():
        yield _empty_catalog_db()

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_browse_requires_no_auth(client: TestClient) -> None:
    """The whole point: an anonymous request (no Authorization header) gets
    the catalog, not a 401."""
    resp = client.get("/api/marketplace/public/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_browse_does_not_accept_or_require_a_token(client: TestClient) -> None:
    """A bogus bearer is simply ignored — the route has no auth dependency."""
    resp = client.get(
        "/api/marketplace/public/themes",
        headers={"Authorization": "Bearer not-a-real-key"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_burst() -> None:
    """Per-IP token bucket: allows up to capacity, then 429s."""
    from fastapi import HTTPException

    from app.routers import marketplace_public

    marketplace_public._BUCKETS.clear()
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.7"},
        client=SimpleNamespace(host="10.0.0.1"),
    )

    # Capacity requests succeed.
    for _ in range(marketplace_public._CAPACITY):
        await marketplace_public._rate_limit(request)  # type: ignore[arg-type]

    # The next one is rejected with 429 + Retry-After.
    with pytest.raises(HTTPException) as exc:
        await marketplace_public._rate_limit(request)  # type: ignore[arg-type]
    assert exc.value.status_code == 429
    assert exc.value.headers is not None
    assert "Retry-After" in exc.value.headers


@pytest.mark.asyncio
async def test_rate_limiter_is_per_ip() -> None:
    """One IP exhausting its bucket does not affect another IP."""
    from app.routers import marketplace_public

    marketplace_public._BUCKETS.clear()
    noisy = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.8"}, client=None
    )
    quiet = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9"}, client=None
    )

    for _ in range(marketplace_public._CAPACITY):
        await marketplace_public._rate_limit(noisy)  # type: ignore[arg-type]

    # A different IP still has a full bucket.
    await marketplace_public._rate_limit(quiet)  # type: ignore[arg-type]
