"""
Redis-backed token bucket rate limiter with in-process fallback.

Used by sensitive endpoints (e.g. secret reveal) to enforce per-user caps.
Key shape: ``tesslate:ratelimit:{scope}:{subject}:{window_start}``.

Falls back to an in-process counter when Redis is unavailable. The fallback
is deliberately weaker (per-process, not cross-pod) but ensures the limiter
is never a single point of failure for the request path.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request

from ..models import User
from ..users import current_active_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process fallback (single-process counters keyed by window)
# ---------------------------------------------------------------------------

_FALLBACK_LOCK = threading.Lock()
_FALLBACK_COUNTERS: dict[str, int] = {}
_FALLBACK_WARNED = False


def _fallback_warn_once() -> None:
    global _FALLBACK_WARNED
    if not _FALLBACK_WARNED:
        _FALLBACK_WARNED = True
        logger.warning(
            "rate_limit: Redis unavailable, using in-process fallback "
            "(per-process counters; not safe across pods)"
        )


def _reset_fallback_for_tests() -> None:
    """Test helper. Not part of the public API."""
    global _FALLBACK_WARNED
    with _FALLBACK_LOCK:
        _FALLBACK_COUNTERS.clear()
        _FALLBACK_WARNED = False


def _fallback_consume(key: str, capacity: int, ttl: int) -> tuple[bool, int]:
    """Increment the in-process counter for ``key``. Returns (allowed, count)."""
    now = time.time()
    expiry_marker = f"{key}:__exp"
    with _FALLBACK_LOCK:
        # Lazy expire: stash a deadline alongside the counter.
        deadline = _FALLBACK_COUNTERS.get(expiry_marker, 0)
        if deadline and now >= deadline:
            _FALLBACK_COUNTERS.pop(key, None)
            _FALLBACK_COUNTERS.pop(expiry_marker, None)
        if key not in _FALLBACK_COUNTERS:
            _FALLBACK_COUNTERS[key] = 0
            _FALLBACK_COUNTERS[expiry_marker] = int(now) + ttl
        _FALLBACK_COUNTERS[key] += 1
        count = _FALLBACK_COUNTERS[key]
    if count > capacity:
        return False, count
    return True, count


# ---------------------------------------------------------------------------
# RedisTokenBucket
# ---------------------------------------------------------------------------


class RedisTokenBucket:
    """Fixed-window counter implemented with Redis ``INCR`` + ``EXPIRE``.

    Single round-trip happy path uses a pipeline (INCR; EXPIRE NX) so that
    only the first request in a window pays for the EXPIRE. Falls back to an
    in-process counter when Redis is unreachable.
    """

    def __init__(self, key_prefix: str = "tesslate:ratelimit") -> None:
        self.key_prefix = key_prefix

    @staticmethod
    def _window_start(window_seconds: int, now: float | None = None) -> int:
        ts = int(now if now is not None else time.time())
        return ts - (ts % window_seconds)

    def _key(self, scope: str, subject: str, window_start: int) -> str:
        return f"{self.key_prefix}:{scope}:{subject}:{window_start}"

    async def check_and_consume(
        self,
        scope: str,
        subject: str,
        *,
        capacity: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        """Increment the bucket and decide whether to allow.

        Returns ``(allowed, remaining, reset_seconds)``. ``remaining`` is the
        number of additional calls permitted in the current window after this
        one (clamped at 0 on rejection). ``reset_seconds`` is seconds until
        the window rolls over.
        """
        now = time.time()
        window_start = self._window_start(window_seconds, now)
        reset_seconds = max(1, (window_start + window_seconds) - int(now))
        key = self._key(scope, subject, window_start)

        client = None
        try:
            from .cache_service import get_redis_client

            client = await get_redis_client()
        except Exception:
            client = None

        if client is None:
            _fallback_warn_once()
            allowed, count = _fallback_consume(key, capacity, window_seconds)
            remaining = max(0, capacity - count)
            return allowed, remaining, reset_seconds

        try:
            pipe = client.pipeline()
            pipe.incr(key)
            # ``nx=True`` only sets the TTL if no TTL is set yet — keeps the
            # window aligned to the first request rather than creeping forward.
            pipe.expire(key, window_seconds, nx=True)
            results = await pipe.execute()
            count = int(results[0])
        except Exception:
            logger.exception("rate_limit: Redis pipeline failed; falling back")
            allowed, count = _fallback_consume(key, capacity, window_seconds)
            remaining = max(0, capacity - count)
            return allowed, remaining, reset_seconds

        if count > capacity:
            return False, 0, reset_seconds
        return True, max(0, capacity - count), reset_seconds


# Module-level singleton — cheap, stateless aside from the prefix.
_BUCKET = RedisTokenBucket()


def get_token_bucket() -> RedisTokenBucket:
    return _BUCKET


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def rate_limited(
    scope: str,
    *,
    capacity: int,
    window_seconds: int,
    audit_action: str | None = None,
) -> Callable[..., Awaitable[User]]:
    """Build a FastAPI dependency that enforces a per-user rate limit.

    Stores the bucket result on ``request.state.rate_limit`` (keyed by scope)
    so handlers can read remaining/limit/reset to set response headers.

    On rejection raises ``HTTPException(429)`` with a ``Retry-After`` header.
    If ``audit_action`` is set, an audit log entry is written best-effort.
    """

    async def _dep(
        request: Request,
        current_user: User = Depends(current_active_user),
    ) -> User:
        bucket = get_token_bucket()
        subject = str(current_user.id)
        allowed, remaining, reset_seconds = await bucket.check_and_consume(
            scope,
            subject,
            capacity=capacity,
            window_seconds=window_seconds,
        )

        # Stash for handler-side header emission.
        store = getattr(request.state, "rate_limit", None)
        if store is None:
            store = {}
            request.state.rate_limit = store
        store[scope] = {
            "limit": capacity,
            "remaining": remaining,
            "reset": reset_seconds,
            "window": window_seconds,
        }

        if not allowed:
            if audit_action:
                # Best-effort audit on rejection. Open a short-lived session so
                # we don't depend on the request's own DB session being open.
                try:
                    from ..database import AsyncSessionLocal

                    team_id = None
                    # Look up team from path params if present (project_id).
                    project_id = request.path_params.get("project_id")
                    if project_id:
                        try:
                            from sqlalchemy import select

                            from ..models import Project

                            async with AsyncSessionLocal() as audit_db:
                                proj = (
                                    await audit_db.execute(
                                        select(Project).where(Project.id == project_id)
                                    )
                                ).scalar_one_or_none()
                                team_id = (
                                    getattr(proj, "team_id", None) if proj is not None else None
                                )
                                if team_id is not None:
                                    await log_event(
                                        db=audit_db,
                                        team_id=team_id,
                                        user_id=current_user.id,
                                        action=audit_action,
                                        resource_type="rate_limit",
                                        details={
                                            "scope": scope,
                                            "capacity": capacity,
                                            "window_seconds": window_seconds,
                                            "path": str(request.url.path),
                                        },
                                        request=request,
                                    )
                                    await audit_db.commit()
                        except Exception:
                            logger.exception(
                                "rate_limit: failed to write rejection audit (non-blocking)"
                            )
                except Exception:
                    logger.exception("rate_limit: audit setup failed (non-blocking)")

            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {scope}",
                headers={
                    "Retry-After": str(reset_seconds),
                    "X-RateLimit-Limit": str(capacity),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                },
            )

        return current_user

    return _dep


# Late import to avoid circular at module load.
from .audit_service import log_event  # noqa: E402
