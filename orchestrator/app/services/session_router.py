"""
Session Router

Maps shell sessions to the pod that owns them for cross-pod visibility.
When running multiple API pod replicas, PTY sessions are inherently pod-local
(they are live processes connected to containers). This router tracks which
pod owns which session, enabling:
- NGINX sticky sessions to route requests to the correct pod
- Session ownership cleanup when pods die
- Error messages when accessing sessions on the wrong pod

Usage:
    from app.services.session_router import get_session_router

    router = get_session_router()
    await router.register_session(session_id)
    is_mine = await router.is_local(session_id)
"""

import logging
import os

logger = logging.getLogger(__name__)

KEY_PREFIX = "tesslate:session_owner:"
SESSION_TTL = 7200  # 2 hours


class SessionRouter:
    """
    Maps shell sessions to their owning pod via Redis.

    Each pod has a unique ID (from HOSTNAME env var or generated).
    When a session is created, it's registered in Redis with the pod ID.
    """

    def __init__(self):
        self.pod_id = os.environ.get("HOSTNAME", f"local-{os.getpid()}")

    async def register_session(self, session_id: str):
        """Register that this pod owns a session."""
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        try:
            key = f"{KEY_PREFIX}{session_id}"
            await redis.setex(key, SESSION_TTL, self.pod_id)
            logger.debug(f"Registered session {session_id} on pod {self.pod_id}")
        except Exception as e:
            logger.debug(f"Failed to register session: {e}")

    async def unregister_session(self, session_id: str):
        """Remove session ownership record."""
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        try:
            key = f"{KEY_PREFIX}{session_id}"
            await redis.delete(key)
        except Exception as e:
            logger.debug(f"Failed to unregister session: {e}")

    async def get_session_owner(self, session_id: str) -> str | None:
        """Get which pod owns a session."""
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return self.pod_id  # Single pod mode — we own everything

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
        from .cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
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
