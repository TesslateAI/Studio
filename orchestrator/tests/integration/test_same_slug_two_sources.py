"""
Wave 5 integration test: same-slug-different-source coexistence.

After alembic 0091 drops the global slug unique constraints on
``marketplace_agents`` (and the other catalog tables), two sources can
each ship a ``coder`` agent. This test asserts the post-migration
behavior end-to-end:

  1. Two MarketplaceAgent rows with slug ``coder`` but different
     ``source_id`` insert successfully.
  2. ``GET /api/marketplace/agents?source=tesslate-official`` returns
     only the official one.
  3. ``GET /api/marketplace/agents?source=<other-handle>`` returns only
     the community-hub one.
  4. ``GET /api/marketplace/agents`` (no ``?source=``) returns both,
     each tagged with the correct ``source_handle``.

We seed the second federated source row directly (no real hub needed)
because the orchestrator browse path reads the local catalog cache, and
that cache is populated by the sync worker — for this test we plant
the cache rows by hand rather than spin up a marketplace service.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_COMMUNITY_SOURCE_ID = uuid.UUID("aabbccdd-1111-2222-3333-444455556666")
_TESSLATE_AGENT_ID = uuid.UUID("aaaa1111-2222-3333-4444-555566667777")
_COMMUNITY_AGENT_ID = uuid.UUID("bbbb2222-3333-4444-5555-666677778888")
_SHARED_SLUG = "wave5-coder"


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    """Same throwaway-loop pattern as test_marketplace_source_aware.py.

    Creates a fresh asyncio loop + asyncpg connection pool per call so
    cross-loop coupling with the FastAPI TestClient is impossible. The
    explicit ``loop.close()`` after ``run_until_complete`` prevents
    asyncpg's protocol futures from outliving the loop they were
    scheduled on (which was the root cause of cross-file
    ``"attached to a different loop"`` errors when this test ran before
    the source-aware suite).
    """

    async def _inner():
        # NullPool ensures each session checks out a fresh connection
        # and releases it on close; nothing lingers in a connection
        # pool that might outlive this loop.
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
        # Drain any lingering tasks so asyncpg's BaseProtocol futures
        # don't get cancelled mid-send (which produces the
        # InternalClientError seen on cross-file teardown).
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

    # The order matters when re-running: drop the agent rows first so the
    # source row delete (if any) doesn't trip the FK.
    await db.execute(
        delete(MarketplaceAgent).where(
            MarketplaceAgent.id.in_([_TESSLATE_AGENT_ID, _COMMUNITY_AGENT_ID])
        )
    )

    src_stmt = pg_insert(MarketplaceSource).values(
        id=_COMMUNITY_SOURCE_ID,
        handle="community-coder-hub",
        display_name="Community Coder Hub",
        base_url="https://community-coder.example.com",
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

    # Two agents, same slug, different source_id.
    for agent_id, source_id, name_suffix in (
        (_TESSLATE_AGENT_ID, _TESSLATE_OFFICIAL_ID, "Tesslate"),
        (_COMMUNITY_AGENT_ID, _COMMUNITY_SOURCE_ID, "Community"),
    ):
        agent_stmt = pg_insert(MarketplaceAgent).values(
            id=agent_id,
            name=f"Wave-5 {name_suffix} Coder",
            slug=_SHARED_SLUG,
            description="Wave 5 coder agent for same-slug coexistence test.",
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
                "slug": agent_stmt.excluded.slug,
                "is_active": True,
                "is_published": True,
                "source_id": source_id,
            },
        )
        await db.execute(agent_stmt)

    await db.commit()


def _seed_sync() -> None:
    _run_db(_seed)


@pytest.mark.integration
def test_same_slug_two_sources_coexist_in_db(authenticated_client):
    """Direct DB assertion: two rows with the same slug, different
    source_ids, must coexist after Wave 5 dropped the global slug
    uniqueness.

    Takes ``authenticated_client`` (even though it doesn't issue HTTP
    requests) to force the session-scoped TestClient + engine to spin up
    BEFORE we call ``_run_db()`` — without this, the first ``_run_db``
    creates and closes a fresh asyncio loop, and a later TestClient
    initialization on a different loop trips
    ``RuntimeError: ... attached to a different loop`` against the
    asyncpg pool.
    """

    async def _go(db):
        from sqlalchemy import select

        from app.models import MarketplaceAgent

        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == _SHARED_SLUG)
        )
        rows = list(result.scalars().all())
        assert len(rows) == 2, (
            f"Expected exactly 2 rows with slug={_SHARED_SLUG!r}, got {len(rows)}. "
            f"If this is 0, the seed failed; if >2, prior runs polluted the DB."
        )
        source_ids = {r.source_id for r in rows}
        assert _TESSLATE_OFFICIAL_ID in source_ids
        assert _COMMUNITY_SOURCE_ID in source_ids

    _seed_sync()
    _run_db(_go)


@pytest.mark.integration
def test_browse_with_tesslate_source_returns_only_official(authenticated_client):
    """``?source=tesslate-official`` returns only the official ``coder``."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/agents?source=tesslate-official")
    assert resp.status_code == 200, resp.text
    agents = [a for a in resp.json().get("agents", []) if a.get("slug") == _SHARED_SLUG]
    assert len(agents) == 1, (
        f"Expected exactly one Tesslate Official {_SHARED_SLUG!r} row, got: "
        f"{[a.get('source_handle') for a in agents]}"
    )
    assert agents[0]["source_handle"] == "tesslate-official"


@pytest.mark.integration
def test_browse_with_community_source_returns_only_community(authenticated_client):
    """``?source=community-coder-hub`` returns only the community ``coder``."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/agents?source=community-coder-hub")
    assert resp.status_code == 200, resp.text
    agents = [a for a in resp.json().get("agents", []) if a.get("slug") == _SHARED_SLUG]
    assert len(agents) == 1, (
        f"Expected exactly one community-coder-hub {_SHARED_SLUG!r} row, got: "
        f"{[a.get('source_handle') for a in agents]}"
    )
    assert agents[0]["source_handle"] == "community-coder-hub"


@pytest.mark.integration
def test_browse_no_source_filter_returns_both(authenticated_client):
    """No ``?source=`` returns rows from every active source — both
    ``coder`` agents must appear, each tagged with its source_handle."""
    _seed_sync()
    client, _ = authenticated_client
    resp = client.get("/api/marketplace/agents?limit=100")
    assert resp.status_code == 200, resp.text
    agents = [a for a in resp.json().get("agents", []) if a.get("slug") == _SHARED_SLUG]
    handles = sorted(a.get("source_handle") for a in agents)
    assert handles == ["community-coder-hub", "tesslate-official"], (
        f"Expected exactly both {_SHARED_SLUG!r} rows from each source, got handles {handles!r}"
    )
