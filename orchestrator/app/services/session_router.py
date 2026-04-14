"""
Session Router

Maps shell sessions to the pod that owns them for cross-pod visibility.
When running multiple API pod replicas, PTY sessions are inherently pod-local
(they are live processes connected to containers). This router tracks which
pod owns which session, enabling:
- NGINX sticky sessions to route requests to the correct pod
- Session ownership cleanup when pods die
- Error messages when accessing sessions on the wrong pod

Backends:
- Redis-backed (cloud): session ownership is written to Redis with a TTL so any
  pod can look up the owner of a given session.
- In-process (desktop sidecar): when ``redis_url`` is empty there is exactly one
  pod, so ownership is tracked in a per-process dict.

Usage:
    from app.services.session_router import get_session_router

    router = get_session_router()
    await router.register_session(session_id)
    is_mine = await router.is_local(session_id)
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

KEY_PREFIX = "tesslate:session_owner:"
SESSION_TTL = 7200  # 2 hours


class SessionRouter:
    """
    Maps shell sessions to their owning pod.

    With ``settings.redis_url`` set: Redis is authoritative; each pod has a
    unique ID (from ``HOSTNAME`` env var or generated at startup).

    Without Redis (desktop sidecar): a process-local dict is used. Since there
    is only one pod in this mode, every session is owned locally.
    """

    def __init__(self):
        self.pod_id = os.environ.get("HOSTNAME", f"local-{os.getpid()}")
        # In-process fallback: {session_id: (pod_id, expires_at_monotonic)}
        self._local_owners: dict[str, tuple[str, float]] = {}

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------
    def _redis_enabled(self) -> bool:
        try:
            from ..config import get_settings

            return bool(getattr(get_settings(), "redis_url", "") or "")
        except Exception:
            return False

    def _local_set(self, session_id: str) -> None:
        self._local_owners[session_id] = (self.pod_id, time.monotonic() + SESSION_TTL)

    def _local_get(self, session_id: str) -> str | None:
        entry = self._local_owners.get(session_id)
        if entry is None:
            return None
        owner, expires_at = entry
        if expires_at <= time.monotonic():
            self._local_owners.pop(session_id, None)
            return None
        return owner

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def register_session(self, session_id: str):
        """Register that this pod owns a session."""
        if not self._redis_enabled():
            self._local_set(session_id)
            return

        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            self._local_set(session_id)
            return

        try:
            key = f"{KEY_PREFIX}{session_id}"
            await redis.setex(key, SESSION_TTL, self.pod_id)
            logger.debug(f"Registered session {session_id} on pod {self.pod_id}")
        except Exception as e:
            logger.debug(f"Failed to register session: {e}")

    async def unregister_session(self, session_id: str):
        """Remove session ownership record."""
        if not self._redis_enabled():
            self._local_owners.pop(session_id, None)
            return

        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            self._local_owners.pop(session_id, None)
            return

        try:
            key = f"{KEY_PREFIX}{session_id}"
            await redis.delete(key)
        except Exception as e:
            logger.debug(f"Failed to unregister session: {e}")

    async def get_session_owner(self, session_id: str) -> str | None:
        """Get which pod owns a session."""
        if not self._redis_enabled():
            return self._local_get(session_id) or self.pod_id

        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return self._local_get(session_id) or self.pod_id

        try:
            key = f"{KEY_PREFIX}{session_id}"
            return await redis.get(key)
        except Exception as e:
            logger.debug(f"Failed to get session owner: {e}")
            return None

    async def is_local(self, session_id: str) -> bool:
        """Check if session is on this pod."""
        owner = await self.get_session_owner(session_id)
        return owner is None or owner == self.pod_id

    async def renew_session(self, session_id: str):
        """Renew session TTL (call on activity)."""
        if not self._redis_enabled():
            # Refresh the in-process entry (only if we own it).
            if session_id in self._local_owners:
                self._local_set(session_id)
            return

        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            if session_id in self._local_owners:
                self._local_set(session_id)
            return

        try:
            key = f"{KEY_PREFIX}{session_id}"
            await redis.expire(key, SESSION_TTL)
        except Exception as e:
            logger.debug(f"Failed to renew session: {e}")


# =============================================================================
# Global Instance
# =============================================================================

_session_router: SessionRouter | None = None


def get_session_router() -> SessionRouter:
    """Get the global SessionRouter instance."""
    global _session_router
    if _session_router is None:
        _session_router = SessionRouter()
    return _session_router


def _reset_session_router_for_tests() -> None:
    """Test-only: clear the cached instance so tests can re-pick the backend."""
    global _session_router
    _session_router = None
