"""Redis-backed lease (Redlock-style ``SET NX EX``).

Uses the existing redis client returned by
:func:`app.services.cache_service.get_redis_client`. If Redis is not
configured or unreachable, raises :class:`LeaseUnavailableError` so
:func:`get_lease_backend` falls back to :class:`DBLease`.

Term semantics
--------------
A separate ``tesslate:lease:{name}:term`` counter is incremented on
every fresh acquire. Renews don't bump it; takeovers do. The counter is
intentionally never decremented — its job is to be monotonic across the
lifetime of the cluster.

Acquire / renew / release each verify that the value stored at the lock
key matches ``"holder:term"`` so a deposed leader can never erase a
fresher leader's lock.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from . import Lease, LeaseToken, LeaseUnavailableError

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _key(name: str) -> str:
    return f"tesslate:lease:{name}"


def _term_key(name: str) -> str:
    return f"tesslate:lease:{name}:term"


# Lua script for atomic compare-and-set on renew. Returns 1 on success,
# 0 if the value mismatched (deposed) or the key is missing.
_LUA_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
else
    return 0
end
"""

# Lua script for atomic compare-and-delete on release.
_LUA_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class RedisLease(Lease):
    """Redlock-style single-instance lease (single redis target).

    Multi-master Redlock is intentionally NOT implemented; the OpenSail
    Redis is a single primary. The DBLease remains the safety net for
    operators who insist on quorum guarantees.
    """

    def __init__(self) -> None:
        # Defer the actual client lookup until first use so importing
        # this module never blocks on Redis.
        self._client = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        from app.services.cache_service import get_redis_client

        client = await get_redis_client()
        if client is None:
            raise LeaseUnavailableError("redis client not configured or unreachable")
        self._client = client
        return client

    async def acquire(
        self, name: str, holder_id: str, ttl_seconds: int
    ) -> Optional[LeaseToken]:
        client = await self._get_client()
        key = _key(name)

        # First INCR the term counter — monotonic across the cluster.
        try:
            term = int(await client.incr(_term_key(name)))
        except Exception as exc:
            logger.warning("RedisLease.acquire: term INCR failed: %s", exc)
            raise LeaseUnavailableError(f"redis INCR failed: {exc}") from exc

        value = f"{holder_id}:{term}"

        # SET NX EX — fails if the key already exists.
        try:
            ok = await client.set(key, value, nx=True, ex=ttl_seconds)
        except Exception as exc:
            logger.warning("RedisLease.acquire: SET NX failed: %s", exc)
            raise LeaseUnavailableError(f"redis SET NX failed: {exc}") from exc

        if not ok:
            # Held by someone else. Try a takeover only if their lock
            # actually expired between our INCR and SET — Redis SETNX +
            # EX is atomic so we don't need a separate TTL check.
            return None

        return LeaseToken(
            name=name,
            holder=holder_id,
            term=term,
            expires_at=_utcnow() + timedelta(seconds=ttl_seconds),
        )

    async def renew(self, token: LeaseToken) -> bool:
        client = await self._get_client()
        value = f"{token.holder}:{token.term}"
        try:
            # Re-extend with a 60s default; the supervisor calls renew
            # well before expiry so this is a generous bound.
            result = await client.eval(_LUA_RENEW, 1, _key(token.name), value, 60)
        except Exception as exc:
            logger.warning("RedisLease.renew: failed: %s", exc)
            return False
        # SET returns "OK" (truthy) on success, 0 on mismatch.
        return result not in (0, b"0", None)

    async def release(self, token: LeaseToken) -> None:
        try:
            client = await self._get_client()
        except LeaseUnavailableError:
            return
        value = f"{token.holder}:{token.term}"
        try:
            await client.eval(_LUA_RELEASE, 1, _key(token.name), value)
        except Exception:
            logger.exception("RedisLease.release: failed for name=%s", token.name)


__all__ = ["RedisLease"]
