"""Unauthenticated marketplace browse API (`/api/marketplace/public`).

A read-only, anonymous mirror of the `tsk_`-authenticated browse endpoints in
`routers/public/marketplace.py`. It exists so that:

  - unpaired desktop clients can browse the production catalog before the user
    signs in to a Tesslate Cloud account, and
  - the marketplace can be embedded / linked from anywhere without an API key.

Only the read-only browse + detail endpoints are mirrored. Purchase-gated
surfaces (`/manifest`, `/skills/{slug}/body`, bundle downloads) stay on the
authenticated router. Like that router, this surface is already limited to
`official` / `admin_trusted` sources, so nothing private is exposed.

Each handler delegates to the authenticated handler. The browse handlers
never read `user` (only the purchase-gated ones do), so the delegation omits
it entirely and there is no query duplication. The only thing this router
adds is the absence of an auth dependency plus a per-IP rate limit (the
authenticated router relies on per-API-key limits, which an anonymous caller
has none of).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .public import marketplace as mp
from .public.marketplace import SortParam

router = APIRouter(prefix="/api/marketplace/public", tags=["marketplace-public"])


# ---------------------------------------------------------------------------
# Per-IP rate limiter — token bucket
# ---------------------------------------------------------------------------
# Anonymous browse has no API key to limit on, so we limit per client IP.
# In-process bucket: sufficient for the browse traffic pattern, and the
# endpoints ship ETag / Cache-Control headers so well-behaved clients rarely
# re-hit. Swap for a Redis bucket if this ever needs to be cross-worker exact.

_CAPACITY = 120          # max burst per IP
_REFILL_PER_SEC = 2.0    # sustained requests/sec per IP
_MAX_TRACKED_IPS = 50_000  # eviction threshold — keeps the bucket map bounded


@dataclass
class _Bucket:
    tokens: float = field(default_factory=lambda: float(_CAPACITY))
    last_refill: float = field(default_factory=time.monotonic)


_BUCKETS: dict[str, _Bucket] = defaultdict(_Bucket)


def _client_ip(request: Request) -> str:
    """Best-effort client IP. Trusts the first `X-Forwarded-For` hop set by
    the ingress; falls back to the socket peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _evict_idle_buckets() -> None:
    """Drop fully-refilled (idle) buckets so the per-IP map cannot grow
    without bound on a public endpoint. An evicted IP simply gets a fresh
    full bucket on its next request, so eviction never tightens a limit."""
    for ip in [ip for ip, b in _BUCKETS.items() if b.tokens >= _CAPACITY]:
        del _BUCKETS[ip]


async def _rate_limit(request: Request) -> None:
    """Per-IP token-bucket dependency. Raises 429 when the bucket is empty."""
    if len(_BUCKETS) > _MAX_TRACKED_IPS:
        _evict_idle_buckets()
    ip = _client_ip(request)
    bucket = _BUCKETS[ip]
    now = time.monotonic()
    bucket.tokens = min(_CAPACITY, bucket.tokens + (now - bucket.last_refill) * _REFILL_PER_SEC)
    bucket.last_refill = now
    if bucket.tokens < 1.0:
        retry_after = int((1.0 - bucket.tokens) / _REFILL_PER_SEC) + 1
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.tokens -= 1.0


_RL = Depends(_rate_limit)


# ---------------------------------------------------------------------------
# Browse + detail — delegate to the authenticated handlers (user omitted)
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace agents (anonymous)."""
    return await mp.list_agents(
        response=response,
        page=page,
        limit=limit,
        category=category,
        pricing_type=pricing_type,
        search=search,
        sort=sort,
        source=source,
        db=db,
    )


@router.get("/agents/{slug}")
async def get_agent(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Agent detail by slug (anonymous)."""
    return await mp.get_agent(slug=slug, response=response, source=source, db=db)


@router.get("/skills")
async def list_skills(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace skills (anonymous)."""
    return await mp.list_skills(
        response=response,
        page=page,
        limit=limit,
        category=category,
        pricing_type=pricing_type,
        search=search,
        sort=sort,
        source=source,
        db=db,
    )


@router.get("/skills/{slug}")
async def get_skill(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Skill detail by slug (anonymous; does not include skill_body)."""
    return await mp.get_skill(slug=slug, response=response, source=source, db=db)


@router.get("/bases")
async def list_bases(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace bases (anonymous)."""
    return await mp.list_bases(
        response=response,
        page=page,
        limit=limit,
        category=category,
        pricing_type=pricing_type,
        search=search,
        sort=sort,
        source=source,
        db=db,
    )


@router.get("/bases/{slug}")
async def get_base(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Base detail by slug (anonymous)."""
    return await mp.get_base(slug=slug, response=response, source=source, db=db)


@router.get("/mcp-servers")
async def list_mcp_servers(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace MCP servers (anonymous)."""
    return await mp.list_mcp_servers(
        response=response,
        page=page,
        limit=limit,
        category=category,
        pricing_type=pricing_type,
        search=search,
        sort=sort,
        source=source,
        db=db,
    )


@router.get("/mcp-servers/{slug}")
async def get_mcp_server(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """MCP server detail by slug (anonymous)."""
    return await mp.get_mcp_server(slug=slug, response=response, source=source, db=db)


@router.get("/themes")
async def list_themes(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: SortParam = "featured",
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace themes (anonymous)."""
    return await mp.list_themes(
        response=response,
        page=page,
        limit=limit,
        category=category,
        pricing_type=pricing_type,
        search=search,
        sort=sort,
        source=source,
        db=db,
    )


@router.get("/themes/{slug}")
async def get_theme(
    slug: str,
    response: Response,
    source: str | None = Query(default=None),
    _rl: None = _RL,
    db: AsyncSession = Depends(get_db),
):
    """Theme detail by slug (anonymous; includes full theme_json)."""
    return await mp.get_theme(slug=slug, response=response, source=source, db=db)
