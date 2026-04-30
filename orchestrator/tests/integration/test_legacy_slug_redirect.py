"""
Wave 5 integration test: legacy bare-slug URLs resolve to Tesslate Official.

Pre-Wave-5 ``/api/marketplace/agents/{slug}`` always returned the unique
row matching the slug. Post-Wave-5 the slug is no longer globally unique
(``coder`` can exist on Tesslate Official AND on a community hub at the
same time). To preserve backwards compatibility with bookmarked /
hardcoded bare-slug URLs:

  - Bare ``GET /api/marketplace/agents/{slug}`` resolves to the Tesslate
    Official row by default.
  - ``GET /api/marketplace/agents/{slug}?source=<handle>`` returns the
    matching row from that source.
  - When no Tesslate Official row exists, the lookup falls back to the
    first matching row (deterministic by source_id ORDER BY) so
    pre-existing community-only slugs still resolve.

This test seeds two rows with the same slug and asserts each resolution
mode returns the right row.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_COMMUNITY_SOURCE_ID = uuid.UUID("ddccbbaa-9999-8888-7777-665544332211")
_TESSLATE_AGENT_ID = uuid.UUID("11112222-aaaa-bbbb-cccc-ddddeeee0001")
_COMMUNITY_AGENT_ID = uuid.UUID("11112222-aaaa-bbbb-cccc-ddddeeee0002")
_SHARED_SLUG = "wave5-redirect-coder"

# Bare-slug agent that exists only on a community hub — used to verify
# the fallback path (no Tesslate Official row → first community row).
_COMMUNITY_ONLY_AGENT_ID = uuid.UUID("11112222-aaaa-bbbb-cccc-ddddeeee0003")
_COMMUNITY_ONLY_SLUG = "wave5-community-only-agent"


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    """Throwaway-loop seed helper. See test_same_slug_two_sources.py for
    the full rationale on the NullPool + manual loop-drain pattern."""

    async def _inner():
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(
            _ASYNC_DB_URL, pool_pre_ping=False, poolclass=NullPool
        )
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_inner())
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        loop.close()


async def _seed(db: AsyncSession) -> None:
    from sqlalchemy import delete
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import MarketplaceAgent, MarketplaceSource

    await db.execute(
        delete(MarketplaceAgent).where(
            MarketplaceAgent.id.in_(
                [_TESSLATE_AGENT_ID, _COMMUNITY_AGENT_ID, _COMMUNITY_ONLY_AGENT_ID]
            )
        )
    )

    src_stmt = pg_insert(MarketplaceSource).values(
        id=_COMMUNITY_SOURCE_ID,
        handle="wave5-redirect-hub",
        display_name="Wave 5 Redirect Hub",
        base_url="https://wave5-redirect.example.com",
        scope="system",
        trust_level="untrusted",
        is_active=True,
    )
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

    # Two same-slug rows on different sources — exercises the explicit
    # ``?source=`` and the default-Tesslate-Official paths.
    for agent_id, source_id, name_suffix in (
        (_TESSLATE_AGENT_ID, _TESSLATE_OFFICIAL_ID, "Official"),
        (_COMMUNITY_AGENT_ID, _COMMUNITY_SOURCE_ID, "Community"),
    ):
        agent_stmt = pg_insert(MarketplaceAgent).values(
            id=agent_id,
            name=f"Wave-5 {name_suffix} Redirect Coder",
            slug=_SHARED_SLUG,
            description="Wave 5 legacy slug redirect test row.",
            category="general",
            item_type="agent",
            pricing_type="free",
            price=0,
            is_active=True,
            is_published=True,
            is_system=False,
            is_builtin=False,
            source_id=source_id,
        )
        agent_stmt = agent_stmt.on_conflict_do_update(
            index_elements=[MarketplaceAgent.id],
            set_={
                "name": agent_stmt.excluded.name,
                "is_active": True,
                "is_published": True,
                "source_id": source_id,
            },
        )
        await db.execute(agent_stmt)

    # Community-only agent — used by the fallback test where no Tesslate
    # Official row exists for the slug.
    community_only_stmt = pg_insert(MarketplaceAgent).values(
        id=_COMMUNITY_ONLY_AGENT_ID,
        name="Wave-5 Community-Only Agent",
        slug=_COMMUNITY_ONLY_SLUG,
        description="Wave 5 legacy slug fallback test row.",
        category="general",
        item_type="agent",
        pricing_type="free",
        price=0,
        is_active=True,
        is_published=True,
        is_system=False,
        is_builtin=False,
        source_id=_COMMUNITY_SOURCE_ID,
    )
    community_only_stmt = community_only_stmt.on_conflict_do_update(
        index_elements=[MarketplaceAgent.id],
        set_={
            "name": community_only_stmt.excluded.name,
            "is_active": True,
            "is_published": True,
            "source_id": _COMMUNITY_SOURCE_ID,
        },
    )
    await db.execute(community_only_stmt)

    await db.commit()


def _seed_sync() -> None:
    _run_db(_seed)


@pytest.mark.integration
def test_bare_slug_url_resolves_to_tesslate_official(authenticated_client):
    """Pre-Wave-5 URLs without ``?source=`` resolve to Tesslate Official."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get(f"/api/marketplace/agents/{_SHARED_SLUG}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == _SHARED_SLUG
    assert body["source_handle"] == "tesslate-official", (
        f"Expected bare-slug URL to default to tesslate-official, got "
        f"source_handle={body.get('source_handle')!r}"
    )
    # Verify the actual row by id.
    assert str(body["id"]) == str(_TESSLATE_AGENT_ID)


@pytest.mark.integration
def test_explicit_source_param_returns_that_source_row(authenticated_client):
    """``?source=<handle>`` returns the row from that source even when a
    Tesslate Official row with the same slug exists."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get(
        f"/api/marketplace/agents/{_SHARED_SLUG}?source=wave5-redirect-hub"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == _SHARED_SLUG
    assert body["source_handle"] == "wave5-redirect-hub"
    assert str(body["id"]) == str(_COMMUNITY_AGENT_ID)


@pytest.mark.integration
def test_bare_slug_url_falls_back_when_no_official_exists(authenticated_client):
    """When no Tesslate Official row exists for the slug, bare-slug
    lookup falls back to the first matching community row (preserving
    pre-Wave-5 single-source URL semantics)."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get(f"/api/marketplace/agents/{_COMMUNITY_ONLY_SLUG}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == _COMMUNITY_ONLY_SLUG
    assert body["source_handle"] == "wave5-redirect-hub"
    assert str(body["id"]) == str(_COMMUNITY_ONLY_AGENT_ID)


@pytest.mark.integration
def test_bare_slug_404_when_no_match_anywhere(authenticated_client):
    """Bare-slug lookup for a non-existent slug returns 404, not 500."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/agents/no-such-agent-anywhere-xyz123")
    assert resp.status_code == 404, resp.text
