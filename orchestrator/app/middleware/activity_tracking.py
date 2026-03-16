"""
Activity Tracking Middleware — updates Project.last_activity for project-scoped requests.

Extracts the project slug from URL paths matching ``/api/projects/{slug}/...``
and fires a non-blocking DB update after the response is sent.  This ensures
the idle monitor has an accurate view of project activity without requiring
every endpoint to manually call ``track_project_activity()``.

Only updates on successful responses (2xx/3xx) to avoid counting failed
auth checks or validation errors.
"""

from __future__ import annotations

import asyncio
import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Match /api/projects/{slug_or_uuid}/... — capture the slug/uuid segment.
# Slugs are lowercase alphanumeric + hyphens; UUIDs have hex + hyphens.
_PROJECT_PATH_RE = re.compile(r"^/api/projects/([a-zA-Z0-9_-]+)")


class ActivityTrackingMiddleware(BaseHTTPMiddleware):
    """Updates Project.last_activity for any request hitting a project-scoped path."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Only track mutating requests (POST/PUT/PATCH/DELETE) that succeed.
        # GETs are excluded to avoid polling endpoints (health checks, status)
        # from resetting the idle timer.
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and 200 <= response.status_code < 400:
            slug = _extract_project_slug(request.url.path)
            if slug:
                # Fire-and-forget — never block the response
                asyncio.create_task(_update_activity(slug))

        return response


def _extract_project_slug(path: str) -> str | None:
    """Return the project slug/uuid from a project-scoped URL, or None."""
    m = _PROJECT_PATH_RE.match(path)
    if not m:
        return None
    slug = m.group(1)
    # Skip list endpoints (no slug) and meta-paths
    if slug in ("", "me", "search", "templates"):
        return None
    return slug


async def _update_activity(slug: str) -> None:
    """Non-blocking DB update for project last_activity."""
    try:
        from ..database import AsyncSessionLocal
        from ..models import Project

        from datetime import UTC, datetime
        from sqlalchemy import update

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Project)
                .where(Project.slug == slug)
                .where(Project.compute_tier == "environment")
                .values(last_activity=datetime.now(UTC))
            )
            await db.commit()
    except Exception:
        # Never let activity tracking break anything
        logger.debug("[ACTIVITY-MW] Failed to update activity for %s", slug, exc_info=True)
