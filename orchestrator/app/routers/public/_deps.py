"""
Shared dependencies for public (`tsk_`-authenticated) routers.

Centralizes three concerns every public endpoint needs:
- scope enforcement (via `require_api_scope`, re-exported here for convenience)
- per-key rate limiting
- audit log entry for write operations

Import pattern:
    from ._deps import scoped, rate_limited, audit_write

`scoped(Permission.X)` replaces the raw `require_api_scope`. It stacks
rate-limit + audit helpers behind a single dependency when both are needed.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_external import get_external_api_user, require_api_scope
from ...database import get_db
from ...models import ExternalAPIKey, User
from ...permissions import Permission

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter — token bucket per ExternalAPIKey.id
# ---------------------------------------------------------------------------
# In-process implementation. Sufficient for single-worker dev and the per-key
# traffic pattern we expect (one desktop client per key). When we scale to
# multi-worker we can swap this for a Redis-backed bucket without changing
# callers.

_DEFAULT_CAPACITY = 60      # max burst
_DEFAULT_REFILL_PER_SEC = 1.0  # sustained rate


@dataclass
class _Bucket:
    tokens: float = field(default_factory=lambda: float(_DEFAULT_CAPACITY))
    last_refill: float = field(default_factory=time.monotonic)


_BUCKETS: dict[UUID, _Bucket] = defaultdict(_Bucket)


def _consume(
    key_id: UUID,
    cost: float,
    capacity: int,
    refill_per_sec: float,
) -> tuple[bool, float]:
    """Try to consume `cost` tokens. Returns (allowed, retry_after_seconds)."""
    bucket = _BUCKETS[key_id]
    now = time.monotonic()
    elapsed = now - bucket.last_refill
    bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_per_sec)
    bucket.last_refill = now
    if bucket.tokens >= cost:
        bucket.tokens -= cost
        return True, 0.0
    deficit = cost - bucket.tokens
    return False, deficit / refill_per_sec


def rate_limited(
    cost: float = 1.0,
    capacity: int = _DEFAULT_CAPACITY,
    refill_per_sec: float = _DEFAULT_REFILL_PER_SEC,
) -> Callable:
    """Dependency factory that applies a per-API-key token bucket.

    Heavy endpoints (sync push, handoff upload) should pass `cost=10` or more
    and/or a smaller `capacity` to prevent abuse.
    """

    async def _check(
        user: User = Depends(get_external_api_user),
    ) -> User:
        key: ExternalAPIKey = user._api_key_record  # type: ignore[attr-defined]
        key_id: UUID = key.id  # type: ignore[assignment]
        allowed, retry_after = _consume(key_id, cost, capacity, refill_per_sec)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        return user

    return _check


# ---------------------------------------------------------------------------
# Audit helper for write endpoints
# ---------------------------------------------------------------------------


async def audit_write(
    *,
    db: AsyncSession,
    user: User,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    project_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Non-blocking audit write keyed on the user's default team.

    Safe to call from any public router. Swallows errors.
    """
    if not user.default_team_id:
        return
    try:
        from ...services.audit_service import log_event

        await log_event(
            db=db,
            team_id=user.default_team_id,
            user_id=user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            details=details,
            request=request,
        )
    except Exception:
        logger.debug("audit_write failed for action=%s", action, exc_info=True)


# ---------------------------------------------------------------------------
# Composite dependency
# ---------------------------------------------------------------------------


def scoped(
    permission: Permission,
    *,
    rate_cost: float = 1.0,
    rate_capacity: int = _DEFAULT_CAPACITY,
    rate_refill_per_sec: float = _DEFAULT_REFILL_PER_SEC,
) -> Callable:
    """Primary public-endpoint dependency: scope + rate limit.

    Returns the authenticated `User`. Use `audit_write(...)` inside the handler
    for write operations (we keep audit out of the dep so handlers can include
    resource_id and project_id captured during the request).
    """

    scope_dep = require_api_scope(permission)

    async def _entry(
        _rl: User = Depends(
            rate_limited(
                cost=rate_cost,
                capacity=rate_capacity,
                refill_per_sec=rate_refill_per_sec,
            )
        ),
        user: User = Depends(scope_dep),
    ) -> User:
        # Both deps resolve `User`; they share the same underlying record via
        # get_external_api_user. Return the scope-checked one (carries
        # _api_scope_used).
        del _rl
        return user

    return _entry


__all__ = [
    "scoped",
    "rate_limited",
    "audit_write",
    "require_api_scope",
    "get_external_api_user",
    "get_db",
]
